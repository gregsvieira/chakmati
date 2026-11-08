import pytest
from fastapi.testclient import TestClient

from chakmati.app.api import create_app
from chakmati.app.engine import Engine
from chakmati.shared.gate.base import GateResult, Route
from chakmati.shared.jobs import JobStore
from chakmati.shared.voice.stt import MAX_AUDIO_BYTES, SpeechToText, TranscribeError

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


# --- what the model invents, and the language it is told to hear ------------------------------------------------------------------------
from chakmati.shared.voice.stt import VOCABULARY, clean  # noqa: E402


class Seg:
    def __init__(self, text, no_speech_prob=0.0, avg_logprob=-0.2):
        self.text, self.no_speech_prob, self.avg_logprob = text, no_speech_prob, avg_logprob


def run(segments, language="pt", info_language="pt"):
    class Info:
        pass

    Info.language = info_language

    class Model:
        def __init__(self):
            self.kwargs = {}

        def transcribe(self, audio, **kwargs):
            self.kwargs = kwargs
            return iter(segments), Info()

    model = Model()
    return SpeechToText("base", loader=lambda name: model, language=language).transcribe(b"A"), model.kwargs


def test_the_language_is_fixed_to_portuguese_by_default_instead_of_guessed():
    (_, _), kwargs = run([Seg("oi")])
    assert kwargs["language"] == "pt"                                  # guessed, short commands came out as English ("Hocus-Hocus all seats...")
    assert kwargs["condition_on_previous_text"] is False and kwargs["temperature"] == 0 and kwargs["beam_size"] == 3
    (_, _), auto = run([Seg("oi")], language="auto", info_language="en")
    assert auto["language"] is None                                    # "auto" is still possible
    assert run([Seg("oi")], language="auto", info_language="en")[0][1] == "en"


def test_the_prompt_is_short_so_it_does_not_leak_into_the_text():
    assert len(VOCABULARY.split()) <= 4 and "Xácmáti" in VOCABULARY and "Alexa" in VOCABULARY
    assert "paizão" not in VOCABULARY                                  # the long list of wake phrases came back as the text on weak audio


@pytest.mark.parametrize("text", ["玉玉。", "Привет", "こんにちは", "안녕", "مرحبا", "Ok 玉"])
def test_text_in_a_script_the_person_does_not_speak_is_dropped(text):
    assert clean(text) == ""
    assert clean(text, "auto") == text.strip()                         # with "auto" nothing is judged by script


def test_a_sentence_repeated_in_a_loop_is_dropped_but_an_honest_repeat_is_kept():
    assert clean("Ôh, Xácmáti. Ôh, Xácmáti. Ôh, Xácmáti. Ôh, Xácmáti.") == ""
    assert clean("Ôh, Xácmáti. Ôh, Xácmáti.") == "Ôh, Xácmáti. Ôh, Xácmáti."
    assert clean("Toca Raul Seixas na Alexa.") == "Toca Raul Seixas na Alexa."
    assert clean("   ") == ""


def test_segments_the_model_calls_silence_are_dropped_and_confident_ones_kept():
    (text, _), _ = run([Seg("Toca Raul Seixas."), Seg("Obrigado.", no_speech_prob=0.9, avg_logprob=-1.5), Seg("na Alexa.", no_speech_prob=0.9, avg_logprob=-0.3)])
    assert text == "Toca Raul Seixas. na Alexa."


def test_the_engine_reads_the_language_from_the_environment():
    from chakmati.shared.config import Settings
    assert Settings.from_env({}).stt_language == "pt"
    assert Settings.from_env({"CHAKMATI_STT_LANGUAGE": "auto"}).stt_language == "auto"
