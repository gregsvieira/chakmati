import pytest

from chakmati.approvals import ActionStore
from chakmati.automations.confirm import verdict
from chakmati.automations.models import parse_spec
from chakmati.automations.service import AutomationService
from chakmati.automations.store import AutomationStore
from chakmati.engine import Engine
from chakmati.gate.base import GateResult, Route
from chakmati.jobs import JobStore


@pytest.mark.parametrize("text, expected", [
    ("sim", "yes"), ("Sim!", "yes"), ("confirmo", "yes"), ("pode criar", "yes"), ("isso mesmo", "yes"), ("Claro.", "yes"),
    ("não", "no"), ("Não, cancela", "no"), ("cancela", "no"), ("deixa pra lá", "no"), ("melhor não", "no"),
    ("sim, mas troque o texto por outra coisa", None), ("quero saber se sim ou não", None), ("quanto é dois mais dois", None), ("", None), ("talvez", None),
])
def test_only_short_whole_replies_are_a_yes_or_a_no(text, expected):
    assert verdict(text) == expected


class FakeGate:
    def __init__(self, route=Route.CHAT):
        self.route = route

    def classify(self, text):
        return GateResult(self.route, 1.0, "fake")


class FakeLLM:
    async def chat(self, messages):
        return "resposta do modelo"


class FakeAssistant:
    def __init__(self, result="Vou responder. Confirma? Diga sim ou não.\n[[action:abc]]"):
        self.result, self.calls, self.choosing = result, [], False

    def awaiting_choice(self, text):
        return self.choosing and text == "Maria Souza"

    async def handle(self, text):
        self.calls.append(text)
        return self.result


class FakeSynth:
    store = type("S", (), {"installed": lambda self: True})()

    def synthesize(self, text, speed="normal"):
        from .test_audio_service import sine_wav

        return sine_wav(0.3)


def make(tmp_path, assistant=None, clock=None):
    clock = clock or [1000.0]
    store, actions = AutomationStore(":memory:"), ActionStore(":memory:")
    service = AutomationService(store, actions, FakeSynth(), tmp_path, now=lambda: clock[0])
    engine = Engine(FakeGate(), FakeLLM(), JobStore(":memory:"), automation_assistant=assistant or FakeAssistant(), automation_service=service, now=lambda: clock[0])
    return engine, service, store, clock


def propose(service):
    return service.propose_create(parse_spec({"name": "Ocupado", "trigger": {"type": "whatsapp_message"}, "action": {"type": "whatsapp_text", "to": "sender", "text": "Estou ocupado"}}))


async def test_saying_yes_creates_the_automation_that_was_waiting(tmp_path):
    engine, service, store, _ = make(tmp_path)
    propose(service)
    reply = await engine.handle("sim")
    assert reply.kind == "answer" and "Ocupado" in reply.text and [a.name for a in store.list()] == ["Ocupado"]
    assert service.pending_confirmation() is None


async def test_saying_no_cancels_it_and_creates_nothing(tmp_path):
    engine, service, store, _ = make(tmp_path)
    propose(service)
    reply = await engine.handle("não, cancela")
    assert "não criei" in reply.text.lower() and store.list() == [] and service.pending_confirmation() is None


async def test_a_yes_with_nothing_waiting_is_just_chat(tmp_path):
    engine, _, store, _ = make(tmp_path)
    reply = await engine.handle("sim")
    assert reply.text == "resposta do modelo" and store.list() == []


async def test_the_stream_confirms_too(tmp_path):
    engine, service, store, _ = make(tmp_path)
    propose(service)
    events = [e async for e in engine.handle_stream("confirmo")]
    assert events[-1]["type"] == "done" and "Ocupado" in events[-1]["result"] and len(store.list()) == 1


async def test_an_automation_request_becomes_a_job_and_the_microphone_stays_open_for_the_answer(tmp_path):
    assistant = FakeAssistant()
    engine, _, _, clock = make(tmp_path, assistant)
    engine._gate = FakeGate(Route.AUTOMATION)
    reply = await engine.handle("crie uma automação")
    assert reply.kind == "job" and reply.route is Route.AUTOMATION
    result = await engine.run_job(engine._store.get(reply.job_id))
    assert "Confirma" in result and assistant.calls == ["crie uma automação"]
    assert engine.awake is True  # the person is asked yes or no: the microphone listens without a wake phrase
    clock[0] += 31
    assert engine.awake is False


async def test_an_answer_to_the_assistants_which_one_question_goes_back_to_it(tmp_path):
    assistant = FakeAssistant("ok")
    assistant.choosing = True
    engine, _, _, _ = make(tmp_path, assistant)
    reply = await engine.handle("Maria Souza")  # the gate alone would call this plain chat
    assert reply.kind == "job" and reply.route is Route.AUTOMATION


async def test_without_the_assistant_the_route_says_automations_are_off(tmp_path):
    engine = Engine(FakeGate(Route.AUTOMATION), FakeLLM(), JobStore(":memory:"))
    reply = await engine.handle("crie uma automação")
    assert "desativ" in (await engine.run_job(engine._store.get(reply.job_id))).lower()


# ----------------------------------------------------------------------------- API
def api_client(tmp_path):
    from fastapi.testclient import TestClient

    from chakmati.api import create_app
    from chakmati.notices import NoticeBoard

    engine, service, store, _ = make(tmp_path)
    app = create_app(engine, engine._store, board=NoticeBoard(), automations=service)
    return TestClient(app), service, store


UI = {"X-LiteAgent-UI": "1"}


def test_api_lists_toggles_and_deletes(tmp_path):
    client, service, store = api_client(tmp_path)
    assert client.get("/automations").json() == []
    auto = store.create(parse_spec({"name": "Ocupado", "trigger": {"type": "whatsapp_message"}, "action": {"type": "whatsapp_text", "to": "sender", "text": "Estou ocupado"}}), 1.0)
    row = client.get("/automations").json()[0]
    assert row["name"] == "Ocupado" and row["enabled"] is True and row["voice"] is False and "Estou ocupado" in row["description"]
    assert client.post(f"/automations/{auto.id}/disable").status_code == 403  # the UI header is required
    assert client.post(f"/automations/{auto.id}/disable", headers=UI).status_code == 200 and store.get(auto.id).enabled is False
    assert client.post(f"/automations/{auto.id}/enable", headers=UI).status_code == 200 and store.get(auto.id).enabled is True
    assert client.delete(f"/automations/{auto.id}").status_code == 403
    assert client.delete(f"/automations/{auto.id}", headers=UI).status_code == 200 and store.list() == []
    assert client.delete(f"/automations/{auto.id}", headers=UI).status_code == 404


def test_api_approves_a_pending_creation_and_serves_the_preview_of_a_voice_one(tmp_path):
    client, service, store = api_client(tmp_path)
    action = service.propose_create(parse_spec({"name": "Voz", "trigger": {"type": "whatsapp_message"}, "action": {"type": "whatsapp_voice", "to": "sender", "text": "Estou ocupado"}}))
    assert any(a["id"] == action.id for a in client.get("/actions").json())
    assert client.get(f"/actions/{action.id}/preview").status_code == 403
    got = client.get(f"/actions/{action.id}/preview", headers=UI)
    assert got.status_code == 200 and got.headers["content-type"] == "audio/ogg" and got.content[:4] == b"OggS"
    assert client.post(f"/actions/{action.id}/approve", headers=UI).status_code == 200
    assert len(store.list()) == 1


# ----------------------------------------------------------------------------- the person's own recorded voice
class FakeStt:
    def transcribe(self, audio):
        return "Estou ocupado, já te respondo", "pt"


def recorded_client(tmp_path, stt=None):
    from fastapi.testclient import TestClient

    from chakmati.api import create_app
    from chakmati.notices import NoticeBoard

    engine, service, store, clock = make(tmp_path)
    app = create_app(engine, engine._store, board=NoticeBoard(), automations=service, stt=stt)
    return TestClient(app), engine, service, store


def test_a_recorded_reply_becomes_a_proposal_with_the_persons_own_voice(tmp_path):
    from .test_audio_service import sine_wav

    client, engine, service, store = recorded_client(tmp_path, FakeStt())
    assert client.post("/automations/recorded", content=sine_wav(2.0), headers={"content-type": "audio/wav"}).status_code == 403
    res = client.post("/automations/recorded", content=sine_wav(2.0), headers={**UI, "content-type": "audio/wav"})
    assert res.status_code == 200
    body = res.json()
    assert body["voice"] is True and body["own"] is True and "sua voz gravada" in body["summary"] and body["transcript"].startswith("Estou ocupado")
    assert store.list() == [] and engine.awake is True  # nothing exists yet; yes / no / redo are heard without a wake phrase
    assert client.get(f"/actions/{body['id']}/preview", headers=UI).content[:4] == b"OggS"
    assert client.post(f"/actions/{body['id']}/approve", headers=UI).status_code == 200
    assert store.list()[0].spec.action["own_voice"] is True


def test_a_recording_over_ten_seconds_or_not_audio_is_refused(tmp_path):
    from .test_audio_service import sine_wav

    client, _, service, _ = recorded_client(tmp_path)
    assert client.post("/automations/recorded", content=sine_wav(14.0), headers={**UI, "content-type": "audio/wav"}).status_code == 422
    assert client.post("/automations/recorded", content=b"junk", headers={**UI, "content-type": "audio/wav"}).status_code == 422
    assert client.post("/automations/recorded", content=b"x", headers={**UI, "content-type": "text/plain"}).status_code == 415
    assert client.post("/automations/recorded", content=b"", headers={**UI, "content-type": "audio/wav"}).status_code == 413
    assert service.pending_confirmation() is None


def test_without_speech_recognition_the_list_still_describes_it(tmp_path):
    from .test_audio_service import sine_wav

    client, _, _, _ = recorded_client(tmp_path)
    body = client.post("/automations/recorded", content=sine_wav(1.0), headers={**UI, "content-type": "audio/wav"}).json()
    assert "voz gravada" in body["summary"]


# ----------------------------------------------------------------------------- an OpenWA that cannot send files
async def test_audio_automations_are_refused_when_whatsapp_cannot_send_audio(tmp_path):
    from chakmati.automations.assistant import AutomationAssistant
    from chakmati.automations.service import AutomationError

    async def no_media():
        return False

    store, actions = AutomationStore(":memory:"), ActionStore(":memory:")
    service = AutomationService(store, actions, FakeSynth(), tmp_path, media_check=no_media)
    with pytest.raises(AutomationError, match="só dá para responder em texto"):
        await service.ensure_audio_possible()

    class LLM:
        async def chat(self, messages):
            return json_intent

    import json as _json

    json_intent = _json.dumps({"action": "create", "when": "message", "reply_mode": "voice", "reply_text": "oi", "include_groups": False})

    class WA:
        async def chats(self, **kw):
            return []

    out = await AutomationAssistant(LLM(), service, WA()).handle("responda em áudio")
    assert "só dá para responder em texto" in out and service.pending_confirmation() is None
    # text replies are unaffected
    json_intent = _json.dumps({"action": "create", "when": "message", "reply_mode": "text", "reply_text": "oi", "include_groups": False})
    assert "Confirma" in await AutomationAssistant(LLM(), service, WA()).handle("responda oi")


def test_the_recorded_endpoint_is_refused_when_audio_is_impossible(tmp_path):
    from fastapi.testclient import TestClient

    from chakmati.api import create_app
    from chakmati.notices import NoticeBoard

    from .test_audio_service import sine_wav

    async def no_media():
        return False

    engine, _, _, _ = make(tmp_path)
    service = AutomationService(AutomationStore(":memory:"), ActionStore(":memory:"), FakeSynth(), tmp_path, media_check=no_media)
    client = TestClient(create_app(engine, engine._store, board=NoticeBoard(), automations=service))
    res = client.post("/automations/recorded", content=sine_wav(1.0), headers={**UI, "content-type": "audio/wav"})
    assert res.status_code == 409 and "texto" in res.json()["detail"]
