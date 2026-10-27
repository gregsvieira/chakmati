import io
import math
import struct
import wave

import pytest

av = pytest.importorskip("av", reason="needs the voice extra (uv sync --extra voice)")

from chakmati.approvals import ActionStore  # noqa: E402
from chakmati.automations.audio import wav_to_ogg_opus
from chakmati.automations.models import SpecError, parse_spec
from chakmati.automations.service import AutomationError, AutomationService
from chakmati.automations.store import AutomationStore


def sine_wav(seconds=1.0, rate=22050) -> bytes:
    frames = b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / rate))) for i in range(int(seconds * rate)))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(frames)
    return buf.getvalue()


def test_a_wav_becomes_a_decodable_ogg_opus_voice_note_of_the_same_length():
    ogg = wav_to_ogg_opus(sine_wav(1.0))
    assert ogg[:4] == b"OggS"
    with av.open(io.BytesIO(ogg)) as container:
        stream = container.streams.audio[0]
        assert stream.codec_context.name == "opus"
        seconds = sum(frame.samples for frame in container.decode(stream)) / 48000
    assert 0.9 < seconds < 1.2


def test_garbage_is_not_converted():
    with pytest.raises(ValueError):
        wav_to_ogg_opus(b"not a wav at all")


class FakeInstalled:
    def installed(self):
        return True


class FakeSynth:
    def __init__(self, installed=True):
        self.store = type("S", (), {"installed": lambda self: installed})()
        self.calls = []

    def synthesize(self, text, speed="normal"):
        self.calls.append((text, speed))
        return sine_wav(0.5)


def make(tmp_path, synth=None, now=lambda: 1000.0):
    store, actions = AutomationStore(":memory:"), ActionStore(":memory:")
    service = AutomationService(store, actions, synth if synth is not None else FakeSynth(), tmp_path, now=now)
    return service, store, actions


def text_spec(**extra):
    return parse_spec({"name": "Ocupado", "trigger": {"type": "whatsapp_message"}, "action": {"type": "whatsapp_text", "to": "sender", "text": "Estou ocupado"}, **extra})


def voice_spec():
    return parse_spec({"name": "Ocupado", "trigger": {"type": "whatsapp_message"}, "action": {"type": "whatsapp_voice", "to": "sender", "text": "Estou ocupado"}})


def test_proposing_creates_nothing_until_it_is_approved(tmp_path):
    service, store, _ = make(tmp_path)
    action = service.propose_create(text_spec())
    assert action.kind == "automation.create" and "Estou ocupado" in action.summary and store.list() == []
    done = service.approve(action.id)
    assert done.status == "executed" and [a.name for a in store.list()] == ["Ocupado"]


def test_a_rejected_proposal_creates_nothing_and_cannot_be_approved_later(tmp_path):
    service, store, _ = make(tmp_path)
    action = service.propose_create(text_spec())
    service.reject(action.id)
    assert store.list() == []
    with pytest.raises(Exception):
        service.approve(action.id)


def test_a_voice_automation_records_the_voice_at_creation_and_keeps_the_recording(tmp_path):
    synth = FakeSynth()
    service, store, _ = make(tmp_path, synth)
    action = service.propose_create(voice_spec())
    assert synth.calls == [("Estou ocupado", "normal")]
    preview = service.preview(action.id)
    assert preview is not None and preview[:4] == b"OggS"  # the person can listen before confirming
    service.approve(action.id)
    auto = store.list()[0]
    assert (tmp_path / f"{auto.id}.ogg").read_bytes()[:4] == b"OggS"
    assert service.preview(action.id) is None  # the proposal's temporary copy is gone


def test_a_voice_automation_needs_the_enhanced_voice(tmp_path):
    service, _, _ = make(tmp_path, FakeSynth(installed=False))
    with pytest.raises(AutomationError, match="Voz melhorada"):
        service.propose_create(voice_spec())
    service2, _, _ = make(tmp_path, synth=None)
    service2._voice = None
    with pytest.raises(AutomationError, match="Voz melhorada"):
        service2.propose_create(voice_spec())


def test_rejecting_a_voice_proposal_removes_its_temporary_recording(tmp_path):
    service, _, _ = make(tmp_path)
    action = service.propose_create(voice_spec())
    assert service.preview(action.id) is not None
    service.reject(action.id)
    assert service.preview(action.id) is None


def test_there_is_a_limit_on_how_many_automations_exist(tmp_path):
    service, store, _ = make(tmp_path)
    for _ in range(AutomationService.MAX_AUTOMATIONS):
        store.create(text_spec(), 1.0)
    with pytest.raises(AutomationError, match="limite"):
        service.propose_create(text_spec())


def test_the_latest_pending_creation_is_the_one_a_spoken_yes_confirms(tmp_path):
    service, _, _ = make(tmp_path)
    assert service.pending_confirmation() is None
    first = service.propose_create(text_spec())
    clock = [2000.0]
    service._now = lambda: clock[0]
    second = service.propose_create(parse_spec({"name": "Outra", "trigger": {"type": "whatsapp_message"}, "action": {"type": "whatsapp_text", "to": "sender", "text": "Outra resposta"}}))
    assert service.pending_confirmation().id == second.id and first.id != second.id
