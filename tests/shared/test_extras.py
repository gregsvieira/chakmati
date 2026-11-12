"""The engine must start and explain itself when the optional pieces (voice, listen) are not installed."""

import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from chakmati.shared import extras
from chakmati.app.api import create_app
from chakmati.shared.approvals import ActionStore
from chakmati.features.automations.audio import wav_to_ogg_opus
from chakmati.features.automations.models import parse_spec
from chakmati.features.automations.service import AutomationError, AutomationService
from chakmati.features.automations.store import AutomationStore
from chakmati.shared.config import Settings
from chakmati.app.engine import Engine
from chakmati.shared.gate.base import GateResult, Route
from chakmati.shared.jobs import JobStore
from chakmati.main import build_app
from chakmati.shared.voice.stt import SpeechToText, TranscribeError
from chakmati.shared.voice.tts import VoiceError, VoiceStore, VoiceSynth, _run_piper



class FakeGate:
    def classify(self, text):
        return GateResult(Route.CHAT, 1.0, "fake")


class FakeLLM:
    async def chat(self, messages):
        return "x"


def hide(monkeypatch, *modules):
    """Make `import <module>` fail, as if the extra had not been installed."""
    for name in modules:
        monkeypatch.setitem(sys.modules, name, None)


# ----------------------------------------------------------------------------- the helper
def test_an_extra_is_available_only_when_all_its_modules_are(monkeypatch):
    found = {"piper", "av"}
    monkeypatch.setattr(extras.importlib.util, "find_spec", lambda name: object() if name in found else None)
    assert extras.available("voice") is True
    assert extras.available("listen") is False  # faster_whisper is missing
    found.discard("av")
    assert extras.available("voice") is False


def test_the_message_says_what_to_install():
    msg = extras.missing_message("listen", "speech recognition")
    assert "speech recognition" in msg and "uv sync --extra listen" in msg
    assert "uv sync --extra voice" in extras.missing_message("voice", "the enhanced voice")


def test_an_unknown_extra_is_a_programming_error():
    with pytest.raises(KeyError):
        extras.available("nope")


# ----------------------------------------------------------------------------- start-up without the extras
def test_the_engine_modules_import_without_the_optional_packages():
    code = (
        "import sys\n"
        "for m in ('av', 'faster_whisper', 'piper', 'numpy', 'onnxruntime'): sys.modules[m] = None\n"
        "import chakmati.app.api, chakmati.main, chakmati.shared.voice.stt, chakmati.shared.voice.tts, chakmati.features.automations.audio, chakmati.features.automations.service\n"
        "print('ok')\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert done.stdout.strip() == "ok"


def test_without_listen_the_app_builds_with_no_speech_recognition(monkeypatch, tmp_path):
    monkeypatch.setattr(extras, "available", lambda name: name != "listen")
    app = build_app(Settings(db_path=":memory:", voices_dir=str(tmp_path), stt_model="base"))
    response = TestClient(app).post("/transcribe", content=b"x", headers={"X-LiteAgent-UI": "1"})
    assert response.status_code == 503
    assert "uv sync --extra listen" in response.json()["detail"]  # says what is missing, not just "off"


# ----------------------------------------------------------------------------- each piece explains itself
def test_speech_recognition_without_faster_whisper_says_what_to_install(monkeypatch):
    hide(monkeypatch, "faster_whisper")
    with pytest.raises(TranscribeError, match="uv sync --extra listen"):
        SpeechToText("base").transcribe(b"audio")


def test_the_voice_without_piper_says_what_to_install(monkeypatch):
    hide(monkeypatch, "piper")
    with pytest.raises(VoiceError, match="uv sync --extra voice"):
        _run_piper("model.onnx", "oi", 1.0)


def test_a_voice_note_without_av_is_a_value_error_naming_the_extra(monkeypatch):
    hide(monkeypatch, "av")
    with pytest.raises(ValueError, match="uv sync --extra voice"):
        wav_to_ogg_opus(b"RIFF")


def test_a_voice_automation_without_the_pieces_is_a_clear_automation_error(monkeypatch, tmp_path):
    hide(monkeypatch, "av")

    class Synth:
        store = type("S", (), {"installed": lambda self: True})()

        def synthesize(self, text, speed="normal"):
            return b"RIFF"

    service = AutomationService(AutomationStore(":memory:"), ActionStore(":memory:"), Synth(), tmp_path)
    spec = parse_spec({"name": "Ocupado", "trigger": {"type": "whatsapp_message"}, "action": {"type": "whatsapp_voice", "to": "sender", "text": "Estou ocupado"}})
    with pytest.raises(AutomationError, match="uv sync --extra voice"):
        service.propose_create(spec)


def test_a_synthesis_failure_in_an_automation_is_an_automation_error(tmp_path):
    class Synth:
        store = type("S", (), {"installed": lambda self: True})()

        def synthesize(self, text, speed="normal"):
            raise VoiceError("the enhanced voice needs piper")

    service = AutomationService(AutomationStore(":memory:"), ActionStore(":memory:"), Synth(), tmp_path)
    spec = parse_spec({"name": "Ocupado", "trigger": {"type": "whatsapp_message"}, "action": {"type": "whatsapp_voice", "to": "sender", "text": "Estou ocupado"}})
    with pytest.raises(AutomationError, match="needs piper"):
        service.propose_create(spec)


# ----------------------------------------------------------------------------- the app learns it from the status
@pytest.mark.parametrize("ready", [True, False])
def test_voice_status_tells_whether_the_engine_piece_is_installed(monkeypatch, tmp_path, ready):
    monkeypatch.setattr(extras, "available", lambda name: ready)
    synth = VoiceSynth(VoiceStore(tmp_path), runner=lambda m, t, s: b"")
    jobs = JobStore(":memory:")
    client = TestClient(create_app(Engine(FakeGate(), FakeLLM(), jobs), jobs, tts=synth))
    assert client.get("/voice/status").json()["engine_ready"] is ready
