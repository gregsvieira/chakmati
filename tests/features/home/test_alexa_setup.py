"""Linking the Alexa through Home Assistant's own setup: right address, nothing kept, and never poking the setup while the person signs in."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from chakmati.app.api import create_app
from chakmati.app.engine import Engine
from chakmati.features.home.alexa_setup import DOMAIN, REGIONS, AlexaSetup, region_for_locale
from chakmati.features.home.api import HomeLink
from chakmati.features.home.auth import HomeAuth
from chakmati.features.home.client import HomeAssistantClient
from chakmati.features.home.models import HomeError
from chakmati.shared.gate.base import GateResult, Route
from chakmati.shared.jobs import JobStore

HA = "http://localhost:8123"
PROXY = HA + "/auth/alexamedia/proxy/01ABC?config_flow_id=01ABC"


class FakeHA:
    """Home Assistant's config flow API, as seen against the real one: start -> a form; the form -> an external step with the sign-in page address."""

    def __init__(self, handler_known=True, external=True, entry=None, user_result=None):
        self.handler_known, self.external, self.entry, self.user_result = handler_known, external, entry, user_result
        self.calls: list = []

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        path, body = request.url.path, (json.loads(request.content) if request.content else None)
        self.calls.append((request.method, path, request.url.query.decode(), body))
        if request.method == "POST" and path == "/api/config/config_entries/flow":
            if not self.handler_known:
                return httpx.Response(404, json={"message": "Invalid handler specified"})
            return httpx.Response(200, json={"type": "form", "flow_id": "01ABC", "step_id": "user", "handler": DOMAIN})
        if request.method == "POST" and path == "/api/config/config_entries/flow/01ABC":
            if self.user_result is not None:
                return httpx.Response(200, json=self.user_result)
            return httpx.Response(200, json={"type": "external", "step_id": "check_proxy", "url": PROXY} if self.external else {"type": "create_entry"})
        if request.method == "GET" and path == "/api/config/config_entries/entry":
            return httpx.Response(200, json=[self.entry] if self.entry else [])
        if request.method == "DELETE":
            return httpx.Response(200, json={"message": "Flow aborted"})
        return httpx.Response(404)


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def make(tmp_path, ha=None):
    ha = ha or FakeHA()
    auth = HomeAuth(str(tmp_path / "auth.json"))
    auth.save(HA, "ACCESS", "REFRESH", 1800, "http://127.0.0.1:8765/")
    clock = Clock()
    return AlexaSetup(auth, ha.client(), clock=clock), ha, clock


async def test_it_starts_the_setup_and_hands_over_the_sign_in_page(tmp_path):
    setup, ha, _ = make(tmp_path)
    out = await setup.start("amazon.com.br", " maria@exemplo.com ", "senha-da-amazon")
    assert out["state"] == "login" and out["url"] == PROXY
    assert ha.calls[0] == ("POST", "/api/config/config_entries/flow", "", {"handler": "alexa_media", "show_advanced_options": False})
    assert ha.calls[1][3] == {"url": "amazon.com.br", "email": "maria@exemplo.com", "password": "senha-da-amazon", "hass_url": HA}   # the address a browser can reach, not homeassistant.local


async def test_nothing_of_the_credentials_stays_in_the_chakmati(tmp_path):
    setup, ha, _ = make(tmp_path)
    await setup.start("amazon.com.br", "maria@exemplo.com", "senha-da-amazon")
    state = json.dumps({k: str(v) for k, v in vars(setup).items() if k not in ("_http", "_auth", "_clock")}) + json.dumps(setup._status)
    assert "senha-da-amazon" not in state and "maria@exemplo.com" not in state
    assert "senha-da-amazon" not in (tmp_path / "auth.json").read_text()
    assert list(tmp_path.iterdir()) == [tmp_path / "auth.json"]                      # no other file was written


@pytest.mark.parametrize("region,email,password,message", [
    ("amazon.xyz", "a@b.co", "x", "país"), ("", "a@b.co", "x", "país"), ("amazon.com.br", "sem-arroba", "x", "e-mail"), ("amazon.com.br", "a@b", "x", "e-mail"),
    ("amazon.com.br", "a b@c.de", "x", "e-mail"), ("amazon.com.br", "a@b.co", "", "senha"), ("amazon.com.br", "a@b.co", "x" * 257, "senha")])
async def test_bad_input_is_refused_before_anything_is_sent(tmp_path, region, email, password, message):
    setup, ha, _ = make(tmp_path)
    with pytest.raises(HomeError, match=message):
        await setup.start(region, email, password)
    assert ha.calls == []


async def test_an_integration_that_is_not_loaded_says_what_to_do(tmp_path):
    setup, *_ = make(tmp_path, FakeHA(handler_known=False))
    with pytest.raises(HomeError, match="reinicie o Home Assistant"):
        await setup.start("amazon.com.br", "a@b.co", "senha")


@pytest.mark.parametrize("result,message", [
    ({"type": "form", "step_id": "proxy_warning"}, "não conseguiu abrir a página de login"),
    ({"type": "form", "step_id": "totp_register"}, "chave de verificação"),
    ({"type": "form", "step_id": "user", "errors": {"base": "x"}}, "recusou o e-mail ou a senha"),
    ({"type": "abort", "reason": "x"}, "não aceitou os dados")])
async def test_any_other_answer_is_a_sentence_and_the_setup_is_dropped(tmp_path, result, message):
    setup, ha, _ = make(tmp_path, FakeHA(user_result=result))
    with pytest.raises(HomeError, match=message):
        await setup.start("amazon.com.br", "a@b.co", "senha")
    assert ha.calls[-1][0] == "DELETE" and (await setup.status())["state"] == "idle"


async def test_waiting_only_reads_the_list_of_configurations_never_the_setup_itself(tmp_path):
    setup, ha, clock = make(tmp_path)
    await setup.start("amazon.com.br", "a@b.co", "senha")
    for _ in range(5):
        clock.now += 20
        assert (await setup.status())["state"] == "login"
    reads = [c for c in ha.calls[2:]]
    assert reads and all(c[0] == "GET" and c[1] == "/api/config/config_entries/entry" and "domain=alexa_media" in c[2] for c in reads)
    assert not any(c[1].startswith("/api/config/config_entries/flow/") and c[0] == "GET" for c in ha.calls)    # a GET there makes Home Assistant move the setup on and kills the sign-in page


async def test_it_finishes_when_the_configuration_appears_loaded(tmp_path):
    setup, ha, _ = make(tmp_path)
    await setup.start("amazon.com.br", "a@b.co", "senha")
    ha.entry = {"domain": "alexa_media", "state": "setup_in_progress"}
    assert (await setup.status())["state"] == "login"
    ha.entry = {"domain": "alexa_media", "state": "loaded"}
    assert await setup.status() == {"state": "done", "message": "A Alexa foi conectada.", "url": ""}
    assert (await setup.status())["state"] == "done"


@pytest.mark.parametrize("state", ["setup_error", "setup_retry", "migration_error"])
async def test_a_configuration_that_fails_to_start_is_an_error(tmp_path, state):
    setup, ha, _ = make(tmp_path)
    await setup.start("amazon.com.br", "a@b.co", "senha")
    ha.entry = {"domain": "alexa_media", "state": state}
    status = await setup.status()
    assert status["state"] == "error" and "não conseguiu iniciar" in status["message"]


async def test_a_sign_in_that_never_ends_is_given_up_and_dropped(tmp_path):
    setup, ha, clock = make(tmp_path)
    await setup.start("amazon.com.br", "a@b.co", "senha")
    clock.now += 11 * 60
    status = await setup.status()
    assert status["state"] == "error" and "demorou demais" in status["message"] and ha.calls[-1][0] == "DELETE"


async def test_cancelling_drops_the_setup_and_a_new_start_cancels_the_old_one(tmp_path):
    setup, ha, _ = make(tmp_path)
    await setup.start("amazon.com.br", "a@b.co", "senha")
    await setup.cancel()
    assert ha.calls[-1] == ("DELETE", "/api/config/config_entries/flow/01ABC", "", None) and (await setup.status())["state"] == "idle"
    await setup.start("amazon.com.br", "a@b.co", "senha")
    await setup.start("amazon.com.br", "a@b.co", "senha")
    assert [c[0] for c in ha.calls].count("DELETE") == 2                          # the first one was dropped before the second began


async def test_not_connected_to_home_assistant_is_a_sentence(tmp_path):
    setup = AlexaSetup(HomeAuth(str(tmp_path / "none.json")), FakeHA().client())
    with pytest.raises(HomeError, match="ainda não está conectado"):
        await setup.start("amazon.com.br", "a@b.co", "senha")


def test_the_regions_and_the_default_for_a_locale():
    assert REGIONS["amazon.com.br"] == "Brasil" and len(REGIONS) == 12
    assert [region_for_locale(x) for x in ("pt-BR", "pt_BR", "en-US", "es-MX", "de-DE", "xx", "")] == ["amazon.com.br", "amazon.com.br", "amazon.com", "amazon.com.mx", "amazon.de", "amazon.com", "amazon.com"]


# --- the routes ------------------------------------------------------------------------------------------------------------------------------------
UI = {"X-LiteAgent-UI": "1"}


class Gate:
    def classify(self, text):
        return GateResult(Route.CHAT, 1.0, "fake")


class LLM:
    async def chat(self, messages):
        return "ok"


def route_client(tmp_path, ha=None):
    ha = ha or FakeHA()
    auth = HomeAuth(str(tmp_path / "auth.json"))
    auth.save(HA, "ACCESS", "REFRESH", 1800, "http://127.0.0.1:8765/")
    link = HomeLink(auth, HomeAssistantClient(auth=auth, transport=httpx.MockTransport(ha.handle)), ha.client(), hosts=[])
    link.alexa = AlexaSetup(auth, ha.client())
    store = JobStore(":memory:")
    return TestClient(create_app(Engine(Gate(), LLM(), store), store, home_link=link), base_url="http://127.0.0.1:8765"), ha


def test_the_routes_need_the_app_window_and_return_the_page_to_show(tmp_path):
    client, ha = route_client(tmp_path)
    body = {"region": "amazon.com.br", "email": "maria@exemplo.com", "password": "senha-da-amazon"}
    assert client.post("/home/alexa", json=body).status_code == 403                      # a web page cannot hand credentials over
    started = client.post("/home/alexa", json=body, headers=UI)
    assert started.status_code == 200 and started.json()["url"] == PROXY
    status = client.get("/home/alexa").json()
    assert status["state"] == "login" and status["regions"]["amazon.com.br"] == "Brasil" and "senha-da-amazon" not in json.dumps(status)
    assert client.delete("/home/alexa").status_code == 403
    assert client.delete("/home/alexa", headers=UI).json()["state"] == "idle"


def test_a_refusal_is_a_sentence_with_a_400(tmp_path):
    client, _ = route_client(tmp_path)
    bad = client.post("/home/alexa", json={"region": "amazon.xyz", "email": "a@b.co", "password": "x"}, headers=UI)
    assert bad.status_code == 400 and "país" in bad.json()["detail"]
    assert client.post("/home/alexa", json={"region": "amazon.com.br", "email": "a@b.co", "password": ""}, headers=UI).status_code == 422
