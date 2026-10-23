import pytest
from fastapi.testclient import TestClient

from liteagent.api import create_app
from liteagent.engine import Engine
from liteagent.gate.base import GateResult, Route
from liteagent.jobs import JobStore
from liteagent.stt import MAX_AUDIO_BYTES, SpeechToText, TranscribeError

UI = {"X-LiteAgent-UI": "1"}


class FakeSegment:
    def __init__(self, text):
        self.text = text


class FakeInfo:
    language = "pt"


class FakeModel:
    def __init__(self):
        self.calls = []

    def transcribe(self, audio, **kwargs):
        self.calls.append((audio.read(), kwargs))
        return iter([FakeSegment(" Olá, "), FakeSegment("Chakmati. ")]), FakeInfo()


def test_transcribe_joins_segments_and_loads_the_model_lazily_once():
    loads = []
    model = FakeModel()
    stt = SpeechToText("base", loader=lambda name: loads.append(name) or model)
    assert loads == []  # nothing loaded (or downloaded) until someone speaks
    assert stt.transcribe(b"AUDIO") == ("Olá, Chakmati.", "pt")
    assert stt.transcribe(b"AUDIO2")[0] == "Olá, Chakmati."
    assert loads == ["base"]
    assert model.calls[0][0] == b"AUDIO" and model.calls[0][1]["vad_filter"] is True
    assert "Xácmáti" in model.calls[0][1]["initial_prompt"]  # the name is given to the recogniser as vocabulary


def test_empty_and_oversized_audio_are_refused_before_the_model_runs():
    stt = SpeechToText("base", loader=lambda name: pytest.fail("must not load"))
    with pytest.raises(TranscribeError, match="empty"):
        stt.transcribe(b"")
    with pytest.raises(TranscribeError, match="large"):
        stt.transcribe(b"x" * (MAX_AUDIO_BYTES + 1))


def test_a_model_failure_becomes_a_transcribe_error():
    class Broken:
        def transcribe(self, audio, **kw):
            raise RuntimeError("decoder blew up")

    with pytest.raises(TranscribeError, match="could not"):
        SpeechToText("base", loader=lambda n: Broken()).transcribe(b"x")


class FakeGate:
    def classify(self, text):
        return GateResult(Route.CHAT, 1.0, "fake")


class FakeLLM:
    async def chat(self, messages):
        return "x"


def make_client(stt):
    store = JobStore(":memory:")
    return TestClient(create_app(Engine(FakeGate(), FakeLLM(), store), store, stt=stt))


def test_transcribe_endpoint_returns_text_and_needs_the_ui_header():
    stt = SpeechToText("base", loader=lambda n: FakeModel())
    client = make_client(stt)
    assert client.post("/transcribe", content=b"AUDIO", headers={"content-type": "audio/webm"}).status_code == 403
    r = client.post("/transcribe", content=b"AUDIO", headers={**UI, "content-type": "audio/webm"})
    assert r.status_code == 200 and r.json() == {"text": "Olá, Chakmati.", "language": "pt", "wake": True, "awake": False}  # greeting him by name is a call


def test_transcribe_endpoint_errors():
    stt = SpeechToText("base", loader=lambda n: FakeModel())
    client = make_client(stt)
    assert client.post("/transcribe", content=b"", headers={**UI, "content-type": "audio/webm"}).status_code == 422
    assert client.post("/transcribe", content=b"x", headers={**UI, "content-type": "text/plain"}).status_code == 415
    assert make_client(None).post("/transcribe", content=b"x", headers={**UI, "content-type": "audio/webm"}).status_code == 503


class WakeModel(FakeModel):
    def transcribe(self, audio, **kwargs):
        return iter([FakeSegment("Ôh, paizão")]), FakeInfo()


def test_transcribe_tells_the_app_when_the_text_is_a_wake_phrase():
    client = make_client(SpeechToText("base", loader=lambda n: WakeModel()))
    r = client.post("/transcribe", content=b"AUDIO", headers={**UI, "content-type": "audio/wav"})
    assert r.json()["wake"] is True and r.json()["text"] == "Ôh, paizão"
