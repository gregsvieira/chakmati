"""Linking the Alexa through Home Assistant's own "Alexa Devices" setup: e-mail, password and the 2-step code, no sign-in page, nothing kept."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from chakmati.app.api import create_app
from chakmati.app.engine import Engine
from chakmati.features.home.alexa_setup import DOMAIN, ERRORS, AlexaSetup
from chakmati.features.home.api import HomeLink
from chakmati.features.home.auth import HomeAuth
from chakmati.features.home.client import HomeAssistantClient
from chakmati.features.home.models import HomeError
from chakmati.shared.gate.base import GateResult, Route
from chakmati.shared.jobs import JobStore

HA = "http://localhost:8123"
FLOW = "/api/config/config_entries/flow"


class FakeHA:
    """Home Assistant's config flow API, as seen against the real one (2026.11): start -> the form; the credentials -> a progress step; reading the flow
    -> the progress until the sign-in ends, then the result: a created entry, or the form again with `errors.base`."""

    def __init__(self, handler_known=True, after=None, progress_reads=1, entry=None):
        self.handler_known, self.after, self.progress_reads = handler_known, after or {"type": "create_entry"}, progress_reads
        self.entry = entry   # the integration's configuration: {"state": ..., "reason": ...}
        self.calls: list = []
        self.reads = 0

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))

    def handle(self, request: httpx.Request) -> httpx.Response:
        path, body = request.url.path, (json.loads(request.content) if request.content else None)
        self.calls.append((request.method, path, body))
        if request.method == "POST" and path == FLOW:
            if not self.handler_known:
                return httpx.Response(404, json={"message": "Invalid handler specified"})
            return httpx.Response(200, json={"type": "form", "flow_id": "01ABC", "step_id": "user", "handler": DOMAIN})
        if request.method == "POST" and path == f"{FLOW}/01ABC":
            return httpx.Response(200, json={"type": "progress", "flow_id": "01ABC", "step_id": "login", "progress_action": "login"})
        if request.method == "GET" and path == f"{FLOW}/01ABC":
            self.reads += 1
            if self.reads <= self.progress_reads:
                return httpx.Response(200, json={"type": "progress", "flow_id": "01ABC", "step_id": "login", "progress_action": "login"})
            return httpx.Response(200, json=self.after)
        if request.method == "GET" and path == "/api/config/config_entries/entry":
            return httpx.Response(200, json=[{"domain": DOMAIN, **self.entry}] if self.entry else [])
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


async def test_it_starts_the_setup_with_the_three_fields_the_integration_asks_for(tmp_path):
    setup, ha, _ = make(tmp_path)
    out = await setup.start(" maria@exemplo.com ", "senha-da-amazon", "123 456")
    assert out == {"state": "login", "message": "Entrando na sua conta Amazon…"}
    assert ha.calls[0] == ("POST", FLOW, {"handler": "alexa_devices", "show_advanced_options": False})
    assert ha.calls[1][2] == {"username": "maria@exemplo.com", "password": "senha-da-amazon", "code": "123456"}


async def test_nothing_of_the_credentials_stays_in_the_chakmati(tmp_path):
    setup, ha, _ = make(tmp_path)
    await setup.start("maria@exemplo.com", "senha-da-amazon", "123456")
    state = json.dumps({k: str(v) for k, v in vars(setup).items() if k not in ("_http", "_auth", "_clock")}) + json.dumps(setup._status)
    assert "senha-da-amazon" not in state and "maria@exemplo.com" not in state and "123456" not in state
    assert "senha-da-amazon" not in (tmp_path / "auth.json").read_text()
    assert list(tmp_path.iterdir()) == [tmp_path / "auth.json"]                      # no other file was written


@pytest.mark.parametrize("email,password,code,message", [
    ("sem-arroba", "x", "123456", "e-mail"), ("a@b", "x", "123456", "e-mail"), ("a b@c.de", "x", "123456", "e-mail"),
    ("a@b.co", "", "123456", "senha"), ("a@b.co", "x" * 257, "123456", "senha"),
    ("a@b.co", "x", "", "código"), ("a@b.co", "x", "12345", "código"), ("a@b.co", "x", "abcdef", "código"), ("a@b.co", "x", "1234567", "código")])
async def test_bad_input_is_refused_before_anything_is_sent(tmp_path, email, password, code, message):
    setup, ha, _ = make(tmp_path)
    with pytest.raises(HomeError, match=message):
        await setup.start(email, password, code)
    assert ha.calls == []


async def test_a_home_assistant_without_the_integration_says_what_is_needed(tmp_path):
    setup, *_ = make(tmp_path, FakeHA(handler_known=False))
    with pytest.raises(HomeError, match="2025.6 ou mais nova"):
        await setup.start("a@b.co", "senha", "123456")


async def test_an_accepted_account_is_not_connected_until_the_devices_are_loaded(tmp_path):
    ha = FakeHA(progress_reads=1, entry={"state": "setup_in_progress"})
    setup, ha, _ = make(tmp_path, ha)
    await setup.start("a@b.co", "senha", "123456")
    assert (await setup.status())["state"] == "login"
    loading = await setup.status()                                                # the setup created the entry: that alone is NOT "connected"
    assert loading["state"] == "loading" and "Carregando" in loading["message"]
    assert (await setup.status())["state"] == "loading"
    ha.entry = {"state": "loaded"}
    assert await setup.status() == {"state": "done", "message": "A Alexa foi conectada."}
    assert (await setup.status())["state"] == "done"                              # and it stays done without asking Home Assistant again
    calls = len(ha.calls)
    await setup.status()
    assert len(ha.calls) == calls


async def test_amazon_asking_to_wait_is_said_plainly_and_is_not_a_failure(tmp_path):
    reason = "Error retrieving data: CannotRetrieveData('Request failed: Too Many Requests')"
    setup, ha, _ = make(tmp_path, FakeHA(progress_reads=0, entry={"state": "setup_retry", "reason": reason}))
    await setup.start("a@b.co", "senha", "123456")
    status = await setup.status()
    assert status["state"] == "waiting" and "Amazon pediu para esperar" in status["message"] and "Não precisa conectar de novo" in status["message"]
    assert "Too Many Requests" not in status["message"]


async def test_another_retry_reason_is_waiting_too_and_a_broken_setup_is_an_error(tmp_path):
    other, *_ = make(tmp_path, FakeHA(progress_reads=0, entry={"state": "setup_retry", "reason": "Error retrieving data: CannotConnect"}))
    await other.start("a@b.co", "senha", "123456")
    status = await other.status()
    assert status["state"] == "waiting" and "ainda não consegui carregar os dispositivos" in status["message"]
    for state in ("setup_error", "migration_error"):
        broken, *_ = make(tmp_path, FakeHA(progress_reads=0, entry={"state": state}))
        await broken.start("a@b.co", "senha", "123456")
        assert (await broken.status())["state"] == "error"


async def test_devices_that_take_long_to_load_become_waiting_and_a_missing_entry_an_error(tmp_path):
    slow, ha, clock = make(tmp_path, FakeHA(progress_reads=0, entry={"state": "setup_in_progress"}))
    await slow.start("a@b.co", "senha", "123456")
    assert (await slow.status())["state"] == "loading"
    clock.now += 5 * 60
    status = await slow.status()
    assert status["state"] == "waiting" and "ainda estão carregando" in status["message"]
    gone, ha2, clock2 = make(tmp_path, FakeHA(progress_reads=0, entry=None))
    await gone.start("a@b.co", "senha", "123456")
    assert (await gone.status())["state"] == "loading"                              # the entry may take a moment to show up
    clock2.now += 20
    assert (await gone.status())["state"] == "error"


async def test_waiting_only_reads_the_setup_and_never_sends_to_it(tmp_path):
    setup, ha, _ = make(tmp_path, FakeHA(progress_reads=3))
    await setup.start("a@b.co", "senha", "123456")
    for _ in range(3):
        await setup.status()
    after_start = ha.calls[2:]
    assert after_start and all(c[0] == "GET" and c[1] == f"{FLOW}/01ABC" for c in after_start)   # a POST there (even an empty one) would reset the sign-in


@pytest.mark.parametrize("key", ["invalid_auth", "cannot_connect", "cannot_retrieve_data"])
async def test_a_refused_sign_in_is_said_in_words(tmp_path, key):
    setup, *_ = make(tmp_path, FakeHA(after={"type": "form", "step_id": "user", "errors": {"base": key}}))
    await setup.start("a@b.co", "senha", "123456")
    await setup.status()
    status = await setup.status()
    assert status == {"state": "error", "message": ERRORS[key]}


async def test_an_unknown_error_and_an_unknown_answer_are_sentences_too(tmp_path):
    setup, *_ = make(tmp_path, FakeHA(after={"type": "form", "step_id": "user", "errors": {"base": "outra_coisa"}}))
    await setup.start("a@b.co", "senha", "123456")
    assert "não aceitou os dados" in (await setup.status())["message"] or "não aceitou os dados" in (await setup.status())["message"]
    other, *_ = make(tmp_path, FakeHA(after={"type": "abort", "reason": "x"}))
    await other.start("a@b.co", "senha", "123456")
    await other.status()
    assert (await other.status())["state"] == "error"


async def test_an_account_that_was_already_connected_is_checked_the_same_way(tmp_path):
    setup, ha, _ = make(tmp_path, FakeHA(progress_reads=0, after={"type": "abort", "reason": "already_configured"}, entry={"state": "loaded"}))
    await setup.start("a@b.co", "senha", "123456")
    assert (await setup.status())["state"] == "done"                                # the abort only says the account exists: whether it works is what the configuration says
    retry, *_ = make(tmp_path, FakeHA(progress_reads=0, after={"type": "abort", "reason": "already_configured"}, entry={"state": "setup_retry", "reason": "Too Many Requests"}))
    await retry.start("a@b.co", "senha", "123456")
    assert (await retry.status())["state"] == "waiting"


async def test_the_second_answer_may_already_be_the_result(tmp_path):
    ha = FakeHA()

    def handle(request):
        if request.method == "POST" and request.url.path == f"{FLOW}/01ABC":
            return httpx.Response(200, json={"type": "form", "step_id": "user", "errors": {"base": "invalid_auth"}})
        return FakeHA.handle(ha, request)
    ha.client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handle))
    setup, *_ = make(tmp_path, ha)
    assert (await setup.start("a@b.co", "senha", "123456"))["state"] == "error"


async def test_a_sign_in_that_never_ends_is_given_up_and_dropped(tmp_path):
    setup, ha, clock = make(tmp_path, FakeHA(progress_reads=10_000))
    await setup.start("a@b.co", "senha", "123456")
    clock.now += 4 * 60
    status = await setup.status()
    assert status["state"] == "error" and "demorou demais" in status["message"]
    assert ha.calls[-1][0] == "DELETE"


async def test_cancelling_drops_the_setup_and_a_new_start_cancels_the_old_one(tmp_path):
    setup, ha, _ = make(tmp_path)
    await setup.start("a@b.co", "senha", "123456")
    await setup.cancel()
    assert ha.calls[-1] == ("DELETE", f"{FLOW}/01ABC", None) and (await setup.status())["state"] == "idle"
    await setup.start("a@b.co", "senha", "123456")
    await setup.start("a@b.co", "senha", "123456")
    assert [c[0] for c in ha.calls].count("DELETE") == 2


async def test_not_connected_to_home_assistant_is_a_sentence(tmp_path):
    auth = HomeAuth(str(tmp_path / "none.json"))
    setup = AlexaSetup(auth, FakeHA().client())
    with pytest.raises(HomeError, match="ainda não está conectado"):
        await setup.start("a@b.co", "senha", "123456")


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


def test_the_routes_need_the_app_window_and_never_return_what_was_typed(tmp_path):
    client, ha = route_client(tmp_path)
    body = {"email": "maria@exemplo.com", "password": "senha-da-amazon", "code": "123456"}
    assert client.post("/home/alexa", json=body).status_code == 403                      # a web page cannot hand credentials over
    started = client.post("/home/alexa", json=body, headers=UI)
    assert started.status_code == 200 and started.json()["state"] == "login"
    status = client.get("/home/alexa").json()
    assert status["state"] == "login" and "regions" not in status
    for text in (json.dumps(started.json()), json.dumps(status)):
        assert "senha-da-amazon" not in text and "123456" not in text and "maria@exemplo.com" not in text
    assert client.delete("/home/alexa").status_code == 403
    assert client.delete("/home/alexa", headers=UI).json()["state"] == "idle"


def test_a_refusal_is_a_sentence_with_a_400(tmp_path):
    client, _ = route_client(tmp_path)
    bad = client.post("/home/alexa", json={"email": "a@b.co", "password": "x", "code": "12"}, headers=UI)
    assert bad.status_code == 400 and "código" in bad.json()["detail"]
    assert client.post("/home/alexa", json={"email": "a@b.co", "password": "", "code": "123456"}, headers=UI).status_code == 422
    assert client.post("/home/alexa", json={"email": "a@b.co", "password": "x"}, headers=UI).status_code == 422     # the code is required
