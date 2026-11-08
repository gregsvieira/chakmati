"""Connecting to Home Assistant with one click: find it, send the person to its login, take the answer, keep the tokens fresh."""

import json
import os
import stat
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from chakmati.app.api import create_app
from chakmati.app.engine import Engine
from chakmati.features.home.api import HomeLink
from chakmati.features.home.auth import NOT_CONNECTED, HomeAuth
from chakmati.features.home.client import HomeAssistantClient
from chakmati.features.home.connect import HomeConnector, discover, lan_url, probe
from chakmati.features.home.models import HomeError
from chakmati.features.home.service import HomeService
from chakmati.shared.approvals import ActionStore
from chakmati.shared.gate.base import GateResult, Route
from chakmati.shared.jobs import JobStore

HA = "http://homeassistant.local:8123"
ENGINE = "http://127.0.0.1:8765/"


# --- addresses ---------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("192.168.0.10", "http://192.168.0.10:8123"),
    ("http://192.168.0.10:8123/", "http://192.168.0.10:8123"),
    ("homeassistant.local", "http://homeassistant.local:8123"),
    ("homeassistant", "http://homeassistant:8123"),
    ("  10.0.0.5:9000 ", "http://10.0.0.5:9000"),
    ("https://ha.local:8123", "https://ha.local:8123"),
    ("localhost:8123", "http://localhost:8123"),
    ("172.16.4.2", "http://172.16.4.2:8123"),
])
def test_an_address_of_the_own_network_is_normalised(raw, expected):
    assert lan_url(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "8.8.8.8", "https://example.com", "http://ha.nabu.casa:443", "ftp://192.168.0.1", "http://", "192.168.0.10:99999"])
def test_anything_else_is_refused_with_a_sentence(raw):
    with pytest.raises(HomeError):
        lan_url(raw)


def test_the_refusal_says_why():
    with pytest.raises(HomeError, match="da sua rede"):
        lan_url("https://example.com")


# --- finding it --------------------------------------------------------------------------------------------------------------------------
def server_with(pages: dict):
    def handler(request: httpx.Request) -> httpx.Response:
        body = pages.get(str(request.url))
        return httpx.Response(200, json=body) if body is not None else httpx.Response(404)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_a_home_assistant_is_recognised_by_its_public_page():
    http = server_with({HA + "/manifest.json": {"name": "Home Assistant", "short_name": "Home Assistant"}})
    assert await probe(HA, http) == {"url": HA, "name": "Home Assistant"}


async def test_the_discovery_info_page_also_counts():
    http = server_with({HA + "/api/discovery_info": {"location_name": "Casa da Maria", "version": "2026.1"}})
    assert await probe(HA, http) == {"url": HA, "name": "Casa da Maria"}


async def test_something_else_on_that_address_is_not_taken_for_one():
    assert await probe(HA, server_with({HA + "/manifest.json": {"name": "Meu roteador"}})) is None
    assert await probe(HA, server_with({})) is None

    def boom(request):
        raise httpx.ConnectError("sem rede")
    assert await probe(HA, httpx.AsyncClient(transport=httpx.MockTransport(boom))) is None


async def test_each_address_that_answers_is_one_result_and_the_first_is_the_usual_name():
    http = server_with({"http://homeassistant.local:8123/manifest.json": {"name": "Home Assistant"}, "http://homeassistant:8123/manifest.json": {"name": "Home Assistant"}})
    assert [f["url"] for f in await discover(http, hosts=[])] == ["http://homeassistant.local:8123", "http://homeassistant:8123"]
    assert await discover(server_with({}), hosts=[]) == []


async def test_this_computer_is_searched_too():
    http = server_with({"http://localhost:8123/manifest.json": {"name": "Home Assistant"}})
    assert [f["url"] for f in await discover(http, hosts=[])] == ["http://localhost:8123"]


# --- the credentials ----------------------------------------------------------------------------------------------------------------------
class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def make_auth(tmp_path, clock=None, token_text=None, url=""):
    legacy = tmp_path / "token.txt"
    if token_text is not None:
        legacy.write_text(token_text)
    return HomeAuth(str(tmp_path / "home_auth.json"), str(legacy), url, clock=clock or Clock())


def token_server(calls: list, answers: list):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((str(request.url), dict(parse_qs(request.content.decode()))))
        status, body = answers.pop(0)
        return httpx.Response(status, json=body)
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_nothing_is_configured_until_the_person_connects(tmp_path):
    auth = make_auth(tmp_path)
    assert not auth.configured and auth.base_url is None
    with pytest.raises(HomeError, match="ainda não está conectado"):
        await auth.bearer(httpx.AsyncClient())
    assert NOT_CONNECTED.startswith("o Home Assistant ainda não")


def test_the_saved_file_is_private(tmp_path):
    auth = make_auth(tmp_path)
    auth.save(HA + "/", "ACCESS", "REFRESH", 1800, ENGINE)
    path = tmp_path / "home_auth.json"
    assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
    assert json.loads(path.read_text())["url"] == HA and auth.configured and auth.oauth and auth.base_url == HA


async def test_a_fresh_access_token_is_used_as_it_is(tmp_path):
    auth = make_auth(tmp_path, Clock(1000.0))
    auth.save(HA, "ACCESS", "REFRESH", 1800, ENGINE)
    calls: list = []
    assert await auth.bearer(token_server(calls, [])) == "ACCESS" and calls == []


async def test_an_expiring_access_token_is_renewed_and_kept(tmp_path):
    clock = Clock(1000.0)
    auth = make_auth(tmp_path, clock)
    auth.save(HA, "OLD", "REFRESH", 1800, ENGINE)
    clock.now += 1800 - 30     # less than a minute left
    calls: list = []
    http = token_server(calls, [(200, {"access_token": "NEW", "expires_in": 1800, "token_type": "Bearer"})])
    assert await auth.bearer(http) == "NEW"
    assert calls == [(HA + "/auth/token", {"grant_type": ["refresh_token"], "refresh_token": ["REFRESH"], "client_id": [ENGINE]})]
    clock.now += 100
    assert await auth.bearer(token_server([], [])) == "NEW"                      # kept: no second call
    assert json.loads((tmp_path / "home_auth.json").read_text())["refresh_token"] == "REFRESH"


async def test_a_refused_renewal_asks_the_person_to_connect_again(tmp_path):
    clock = Clock(1000.0)
    auth = make_auth(tmp_path, clock)
    auth.save(HA, "OLD", "REFRESH", 10, ENGINE)
    with pytest.raises(HomeError, match="conecte de novo"):
        await auth.bearer(token_server([], [(400, {"error": "invalid_grant"})]))
    assert auth.configured                                                    # nothing is thrown away on a hiccup


async def test_the_older_way_still_works_and_the_connect_flow_wins_over_it(tmp_path):
    auth = make_auth(tmp_path, token_text="LONGLIVED\n", url="http://192.168.0.5:8123/")
    assert auth.configured and not auth.oauth and auth.base_url == "http://192.168.0.5:8123"
    assert await auth.bearer(httpx.AsyncClient()) == "LONGLIVED"
    auth.save(HA, "ACCESS", "REFRESH", 1800, ENGINE)
    assert auth.oauth and auth.base_url == HA and await auth.bearer(httpx.AsyncClient()) == "ACCESS"
    auth.forget()                                                             # disconnect: only what the connect flow wrote is removed
    assert not auth.oauth and auth.configured and auth.base_url == "http://192.168.0.5:8123"


def test_a_token_without_an_address_is_not_a_connection(tmp_path):
    assert not make_auth(tmp_path, token_text="TOKEN", url="").configured


# --- the sign-in -------------------------------------------------------------------------------------------------------------------------
def make_connector(tmp_path, answers=None, clock=None):
    clock = clock or Clock()
    auth = make_auth(tmp_path, clock)
    calls: list = []
    return HomeConnector(auth, token_server(calls, answers or []), now=clock), auth, calls, clock


def test_start_gives_the_login_page_of_the_home_assistant_with_a_way_back_to_the_engine(tmp_path):
    connector, _, _, _ = make_connector(tmp_path)
    url = connector.start("homeassistant.local", ENGINE)
    parts = urlsplit(url)
    query = {k: v[0] for k, v in parse_qs(parts.query).items()}
    assert f"{parts.scheme}://{parts.netloc}{parts.path}" == HA + "/auth/authorize"
    assert query["client_id"] == ENGINE and query["redirect_uri"] == ENGINE + "home/callback" and len(query["state"]) >= 24
    assert connector.pending


@pytest.mark.parametrize("home,engine", [("https://example.com", ENGINE), ("8.8.8.8", ENGINE), ("192.168.0.10", "http://evil.example/"), ("192.168.0.10", "http://192.168.0.5:8765/")])
def test_start_refuses_a_stranger_on_either_side(tmp_path, home, engine):
    connector, _, _, _ = make_connector(tmp_path)
    with pytest.raises(HomeError):
        connector.start(home, engine)
    assert not connector.pending


async def test_finish_exchanges_the_code_and_keeps_the_tokens(tmp_path):
    connector, auth, calls, _ = make_connector(tmp_path, [(200, {"access_token": "A", "refresh_token": "R", "expires_in": 1800, "token_type": "Bearer"})])
    state = parse_qs(urlsplit(connector.start("192.168.0.10", ENGINE)).query)["state"][0]
    assert await connector.finish(state, "CODE") == "http://192.168.0.10:8123"
    assert calls == [("http://192.168.0.10:8123/auth/token", {"grant_type": ["authorization_code"], "code": ["CODE"], "client_id": [ENGINE]})]
    assert auth.oauth and auth.base_url == "http://192.168.0.10:8123" and not connector.pending


async def test_a_wrong_expired_or_reused_state_is_refused_and_saves_nothing(tmp_path):
    connector, auth, calls, clock = make_connector(tmp_path, [(200, {"access_token": "A", "refresh_token": "R"})] * 3)
    connector.start("192.168.0.10", ENGINE)
    with pytest.raises(HomeError, match="já foi usado ou expirou"):
        await connector.finish("not-the-state", "CODE")
    state = parse_qs(urlsplit(connector.start("192.168.0.10", ENGINE)).query)["state"][0]
    clock.now += 601
    with pytest.raises(HomeError):
        await connector.finish(state, "CODE")
    with pytest.raises(HomeError):                                            # nothing pending at all
        await connector.finish(state, "CODE")
    assert calls == [] and not auth.configured


async def test_home_assistant_saying_no_is_reported(tmp_path):
    connector, auth, _, _ = make_connector(tmp_path, [(400, {"error": "invalid_request"})])
    state = parse_qs(urlsplit(connector.start("192.168.0.10", ENGINE)).query)["state"][0]
    with pytest.raises(HomeError, match="não aceitou"):
        await connector.finish(state, "CODE")
    assert not auth.configured


# --- the client with these credentials ------------------------------------------------------------------------------------------------------
async def test_the_client_uses_the_connected_address_and_renews_a_rejected_token_once(tmp_path):
    clock = Clock(1000.0)
    auth = make_auth(tmp_path, clock)
    auth.save(HA, "STALE", "REFRESH", 1800, ENGINE)
    seen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.headers.get("authorization")))
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "FRESH", "expires_in": 1800})
        return httpx.Response(401) if request.headers.get("authorization") == "Bearer STALE" else httpx.Response(200, json=[
            {"entity_id": "media_player.echo", "state": "idle", "attributes": {"friendly_name": "Echo"}}])

    client = HomeAssistantClient(auth=auth, transport=httpx.MockTransport(handler))
    assert [e.id for e in await client.entities()] == ["media_player.echo"]
    assert seen == [("/api/states", "Bearer STALE"), ("/auth/token", None), ("/api/states", "Bearer FRESH")]


async def test_the_client_before_connecting_says_so(tmp_path):
    client = HomeAssistantClient(auth=make_auth(tmp_path))
    with pytest.raises(HomeError, match="ainda não está conectado"):
        await client.entities()


async def test_a_token_that_stays_rejected_asks_to_connect_again(tmp_path):
    auth = make_auth(tmp_path)
    auth.save(HA, "A", "R", 1800, ENGINE)

    def handler(request):
        return httpx.Response(200, json={"access_token": "B", "expires_in": 1800}) if request.url.path == "/auth/token" else httpx.Response(401)

    with pytest.raises(HomeError, match="conecte de novo"):
        await HomeAssistantClient(auth=auth, transport=httpx.MockTransport(handler)).entities()


# --- the routes -----------------------------------------------------------------------------------------------------------------------------
UI = {"X-LiteAgent-UI": "1"}


class FakeGate:
    def classify(self, text):
        return GateResult(Route.CHAT, 1.0, "fake")


class FakeLLM:
    async def chat(self, messages):
        return "ok"


def build(tmp_path, entities=()):
    clock = Clock()
    auth = make_auth(tmp_path, clock)
    seen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        if request.url.path == "/manifest.json" and request.url.host == "homeassistant.local":
            return httpx.Response(200, json={"name": "Home Assistant"})
        if request.url.path == "/auth/token":
            return httpx.Response(200, json={"access_token": "ACCESS", "refresh_token": "REFRESH", "expires_in": 1800})
        if request.url.path == "/api/states":
            return httpx.Response(200, json=list(entities))
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    link = HomeLink(auth, HomeAssistantClient(auth=auth, transport=transport), httpx.AsyncClient(transport=transport), hosts=[])
    link.connector._now = clock
    store = JobStore(":memory:")
    home = HomeService(link.client, ActionStore(":memory:"))
    app = create_app(Engine(FakeGate(), FakeLLM(), store), store, home=home, home_link=link)
    return TestClient(app, base_url="http://127.0.0.1:8765"), link, auth, seen


def test_discover_lists_what_was_found(tmp_path):
    client, *_ = build(tmp_path)
    assert client.get("/home/discover").json() == {"found": [{"url": "http://homeassistant.local:8123", "name": "Home Assistant"}]}


def test_the_whole_connection_from_the_click_to_the_tokens(tmp_path):
    echo = {"entity_id": "media_player.echo_sala", "state": "playing", "attributes": {"friendly_name": "Echo Dot da sala"}}
    client, link, auth, seen = build(tmp_path, [echo, {"entity_id": "light.sala", "state": "on", "attributes": {"friendly_name": "Luz"}}])
    assert client.get("/home/status").json()["connected"] is False
    assert client.post("/home/connect", json={"url": "homeassistant.local"}).status_code == 403          # a web page cannot start it
    started = client.post("/home/connect", json={"url": "homeassistant.local"}, headers=UI).json()
    query = parse_qs(urlsplit(started["authorize_url"]).query)
    assert started["authorize_url"].startswith("http://homeassistant.local:8123/auth/authorize?") and query["redirect_uri"] == ["http://127.0.0.1:8765/home/callback"]
    assert client.get("/home/status").json()["pending"] is True
    page = client.get("/home/callback", params={"state": query["state"][0], "code": "CODE"})            # what the browser does after "Aprovar"
    assert page.status_code == 200 and "Pronto!" in page.text and "Pode fechar esta janela" in page.text
    assert auth.oauth
    status = client.get("/home/status").json()
    assert status["connected"] is True and status["url"] == "http://homeassistant.local:8123" and status["pending"] is False
    assert status["players"] == [{"name": "Echo Dot da sala", "state": "playing"}] and "alexa_devices" in status["alexa_help"]


def test_a_callback_with_the_wrong_state_connects_nothing(tmp_path):
    client, _, auth, _ = build(tmp_path)
    client.post("/home/connect", json={"url": "192.168.0.10"}, headers=UI)
    page = client.get("/home/callback", params={"state": "forged", "code": "CODE"})
    assert "Não consegui conectar" in page.text and not auth.configured


def test_cancelling_in_home_assistant_is_said_kindly(tmp_path):
    client, link, auth, _ = build(tmp_path)
    client.post("/home/connect", json={"url": "192.168.0.10"}, headers=UI)
    page = client.get("/home/callback", params={"error": "access_denied", "state": "x"})
    assert "Conexão cancelada" in page.text and not auth.configured and link.connector.pending is False


def test_a_stranger_s_address_is_refused_with_a_sentence(tmp_path):
    client, *_ = build(tmp_path)
    bad = client.post("/home/connect", json={"url": "https://example.com"}, headers=UI)
    assert bad.status_code == 400 and "da sua rede" in bad.json()["detail"]


def test_the_page_never_repeats_what_the_address_bar_said(tmp_path):
    client, *_ = build(tmp_path)
    page = client.get("/home/callback", params={"state": "<script>alert(1)</script>", "code": "x"})
    assert "<script>alert" not in page.text


def test_status_says_when_home_assistant_cannot_be_reached(tmp_path):
    client, link, auth, _ = build(tmp_path)
    auth.save("http://192.168.0.99:8123", "A", "R", 1800, ENGINE)

    def broken(request):
        raise httpx.ConnectError("sem rede")
    link.client._http = httpx.AsyncClient(transport=httpx.MockTransport(broken))
    status = client.get("/home/status").json()
    assert status["configured"] is True and status["connected"] is False and "inacessível" in status["error"]


def test_disconnecting_forgets_the_tokens(tmp_path):
    client, _, auth, _ = build(tmp_path)
    auth.save(HA, "A", "R", 1800, ENGINE)
    assert client.delete("/home").status_code == 403
    assert client.delete("/home", headers=UI).json()["configured"] is False and not auth.oauth


def test_the_overview_tells_the_desktop_what_is_connected(tmp_path):
    echo = {"entity_id": "media_player.echo_sala", "state": "idle", "attributes": {"friendly_name": "Echo Dot da sala"}}
    client, _, auth, _ = build(tmp_path, [echo])
    assert client.get("/overview").json()["home"]["connected"] is False
    auth.save(HA, "A", "R", 1800, ENGINE)
    home = client.get("/overview").json()["home"]
    assert home["enabled"] is True and home["connected"] is True and home["players"] == [{"name": "Echo Dot da sala", "state": "idle"}]


# --- searching the own network --------------------------------------------------------------------------------------------------------------
def test_the_own_network_is_the_other_254_addresses_of_the_slash_24(monkeypatch):
    class FakeSocket:
        def __init__(self, *a): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def connect(self, addr): pass
        def getsockname(self): return ("192.168.0.3", 40000)
    monkeypatch.setattr("chakmati.features.home.connect.socket.socket", FakeSocket)
    from chakmati.features.home.connect import own_hosts
    hosts = own_hosts()
    assert len(hosts) == 253 and "192.168.0.3" not in hosts and hosts[0] == "192.168.0.1" and hosts[-1] == "192.168.0.254"


@pytest.mark.parametrize("address", ["8.8.8.8", "127.0.0.1", "100.64.0.5"])
def test_a_network_that_is_not_the_persons_own_is_never_scanned(monkeypatch, address):
    class FakeSocket:
        def __init__(self, *a): pass
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def connect(self, addr): pass
        def getsockname(self): return (address, 1)
    monkeypatch.setattr("chakmati.features.home.connect.socket.socket", FakeSocket)
    from chakmati.features.home.connect import own_hosts
    assert own_hosts() == []


def test_no_network_card_means_nothing_to_scan(monkeypatch):
    def broken(*a):
        raise OSError("sem rede")
    monkeypatch.setattr("chakmati.features.home.connect.socket.socket", broken)
    from chakmati.features.home.connect import own_hosts
    assert own_hosts() == []


async def test_the_scan_finds_a_home_assistant_on_a_listening_address_and_ignores_the_rest():
    import asyncio
    from chakmati.features.home.connect import scan

    async def serve(reader, writer):
        writer.close()
    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    pages = {f"http://127.0.0.1:{port}/manifest.json": {"name": "Home Assistant"}}
    try:
        found = await scan(server_with(pages), ["127.0.0.1", "127.0.0.2"], port=port, timeout=0.3)
    finally:
        server.close()
        await server.wait_closed()
    assert found == [{"url": f"http://127.0.0.1:{port}", "name": "Home Assistant"}]       # 127.0.0.2 has nothing listening: skipped without a page request


async def test_something_listening_that_is_not_a_home_assistant_is_not_one():
    import asyncio
    from chakmati.features.home.connect import scan

    async def serve(reader, writer):
        writer.close()
    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        assert await scan(server_with({f"http://127.0.0.1:{port}/manifest.json": {"name": "Minha impressora"}}), ["127.0.0.1"], port=port, timeout=0.3) == []
    finally:
        server.close()
        await server.wait_closed()


async def test_a_slow_name_does_not_hold_the_search_back(monkeypatch):
    import asyncio
    import time
    from chakmati.features.home import connect

    async def slow_probe(url, http):
        if "homeassistant.local" in url:
            await asyncio.sleep(30)          # a .local lookup that never answers
        return {"url": url, "name": "Home Assistant"} if url == "http://localhost:8123" else None
    monkeypatch.setattr(connect, "probe", slow_probe)
    monkeypatch.setattr(connect, "NAME_TIMEOUT_SECONDS", 0.2)
    started = time.perf_counter()
    assert [f["url"] for f in await connect.discover(None, hosts=[])] == ["http://localhost:8123"]
    assert time.perf_counter() - started < 2


async def test_the_names_and_the_scan_run_together_and_both_are_listed(monkeypatch):
    from chakmati.features.home import connect

    async def fake_probe(url, http):
        return {"url": url, "name": "Home Assistant"} if url in ("http://homeassistant.local:8123", "http://192.168.0.7:8123") else None

    async def fake_scan(http, hosts, **kw):
        return [await fake_probe(f"http://{h}:8123", http) for h in hosts if h == "192.168.0.7"]
    monkeypatch.setattr(connect, "probe", fake_probe)
    monkeypatch.setattr(connect, "scan", fake_scan)
    found = await connect.discover(None, hosts=["192.168.0.7", "192.168.0.8"])
    assert [f["url"] for f in found] == ["http://homeassistant.local:8123", "http://192.168.0.7:8123"]    # the usual name first
