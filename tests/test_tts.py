import asyncio
import hashlib
import io
import wave

import httpx
import pytest
from fastapi.testclient import TestClient

from chakmati.api import create_app
from chakmati.engine import Engine
from chakmati.gate.base import GateResult, Route
from chakmati.jobs import JobStore
from chakmati.tts import MAX_TEXT, VoiceError, VoiceFile, VoiceStore, VoiceSynth

UI = {"X-LiteAgent-UI": "1"}
MODEL = b"fake-onnx-model-bytes" * 50
CONFIG = b'{"audio": {"sample_rate": 22050}}'


def files(model=MODEL, config=CONFIG, host="https://huggingface.co"):
    return (
        VoiceFile("voice.onnx", f"{host}/rhasspy/piper-voices/resolve/main/voice.onnx", len(model), hashlib.sha256(model).hexdigest()),
        VoiceFile("voice.onnx.json", f"{host}/rhasspy/piper-voices/resolve/main/voice.onnx.json", len(config), hashlib.sha256(config).hexdigest()),
    )


def serving(model=MODEL, config=CONFIG):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=model if request.url.path.endswith(".onnx") else config)

    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True)


# ----------------------------------------------------------------------------- downloading
async def test_download_verifies_and_installs_atomically(tmp_path):
    store = VoiceStore(tmp_path, files(), client_factory=serving())
    assert store.status()["installed"] is False
    await store.download()
    status = store.status()
    assert status["installed"] is True and status["downloading"] is False and status["error"] is None
    assert (tmp_path / "voice.onnx").read_bytes() == MODEL
    assert not list(tmp_path.glob("*.part"))
    await store.download()  # already there: nothing to do, no error
    assert store.status()["installed"] is True


async def test_a_corrupted_download_is_rejected_and_leaves_nothing_behind(tmp_path):
    store = VoiceStore(tmp_path, files(), client_factory=serving(model=b"tampered" * 100))
    await store.download()
    status = store.status()
    assert status["installed"] is False and "hash" in status["error"] or "size" in status["error"]
    assert not (tmp_path / "voice.onnx").exists() and not list(tmp_path.glob("*.part"))


async def test_a_failed_request_is_reported_not_raised(tmp_path):
    client = lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404)))  # noqa: E731
    store = VoiceStore(tmp_path, files(), client_factory=client)
    await store.download()
    assert store.status()["installed"] is False and "404" in store.status()["error"]


def test_only_the_official_voice_repository_can_be_downloaded_from(tmp_path):
    with pytest.raises(VoiceError, match="host"):
        VoiceStore(tmp_path, files(host="https://evil.example.com"))
    with pytest.raises(VoiceError, match="https"):
        VoiceStore(tmp_path, files(host="http://huggingface.co"))


async def test_progress_is_reported_while_downloading(tmp_path):
    seen = []
    store = VoiceStore(tmp_path, files(), client_factory=serving())
    original = store._set_progress

    def spy(done, total):
        original(done, total)
        seen.append(store.status()["progress"])

    store._set_progress = spy
    await store.download()
    assert seen and seen[-1] == 1.0 and seen == sorted(seen)


async def test_remove_deletes_the_files(tmp_path):
    store = VoiceStore(tmp_path, files(), client_factory=serving())
    await store.download()
    store.remove()
    assert store.status()["installed"] is False and not (tmp_path / "voice.onnx").exists()


async def test_a_second_download_while_one_runs_does_not_start_another(tmp_path):
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, content=MODEL if request.url.path.endswith(".onnx") else CONFIG)

    store = VoiceStore(tmp_path, files(), client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    first = asyncio.create_task(store.download())
    second = asyncio.create_task(store.download())
    await asyncio.gather(first, second)
    assert calls.count("/rhasspy/piper-voices/resolve/main/voice.onnx") == 1


# ----------------------------------------------------------------------------- synthesis
class FakeChunk:
    def __init__(self, samples):
        import numpy as np

        self.audio_float_array = np.asarray(samples, dtype="float32")


class FakeVoice:
    class config:
        sample_rate = 22050

    def __init__(self):
        self.calls = []

    def synthesize(self, text, syn_config=None):
        self.calls.append((text, syn_config))
        yield FakeChunk([0.0, 0.5, -0.5, 0.25])
        yield FakeChunk([0.1, 0.1])


def installed_store(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "voice.onnx").write_bytes(MODEL)
    (tmp_path / "voice.onnx.json").write_bytes(CONFIG)
    return VoiceStore(tmp_path, files())


def test_synthesize_returns_a_valid_wav_and_loads_the_voice_once(tmp_path):
    pytest.importorskip("numpy", reason="needs the voice extra (uv sync --extra voice)")
    voice = FakeVoice()
    loads = []
    synth = VoiceSynth(installed_store(tmp_path), loader=lambda path: loads.append(path) or voice)
    wav = synth.synthesize("Fala paizão!")
    synth.synthesize("de novo")
    assert len(loads) == 1 and loads[0].endswith("voice.onnx")
    with wave.open(io.BytesIO(wav)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()) == (1, 2, 22050, 6)


def test_fast_speed_shortens_the_phrase_by_scaling_its_length(tmp_path):
    pytest.importorskip("numpy", reason="needs the voice extra (uv sync --extra voice)")
    voice = FakeVoice()
    synth = VoiceSynth(installed_store(tmp_path), loader=lambda p: voice)
    synth.synthesize("oi", speed="normal")
    synth.synthesize("oi", speed="fast")
    normal, fast = voice.calls[0][1], voice.calls[1][1]
    assert (normal is None or normal.length_scale == 1.0) and fast.length_scale == pytest.approx(0.85)


def test_synthesize_refuses_when_not_installed_or_the_text_is_bad(tmp_path):
    empty = VoiceSynth(VoiceStore(tmp_path / "none", files()), loader=lambda p: pytest.fail("must not load"))
    with pytest.raises(VoiceError, match="not installed"):
        empty.synthesize("oi")
    synth = VoiceSynth(installed_store(tmp_path), loader=lambda p: FakeVoice())
    with pytest.raises(VoiceError, match="empty"):
        synth.synthesize("   ")
    with pytest.raises(VoiceError, match="long"):
        synth.synthesize("a" * (MAX_TEXT + 1))
    with pytest.raises(VoiceError, match="speed"):
        synth.synthesize("oi", speed="warp")


# ----------------------------------------------------------------------------- HTTP
class FakeGate:
    def classify(self, text):
        return GateResult(Route.CHAT, 1.0, "fake")


class FakeLLM:
    async def chat(self, messages):
        return "x"


def make_client(tmp_path, installed=True):
    store = installed_store(tmp_path) if installed else VoiceStore(tmp_path, files(), client_factory=serving())
    synth = VoiceSynth(store, loader=lambda p: FakeVoice())
    jobs = JobStore(":memory:")
    return TestClient(create_app(Engine(FakeGate(), FakeLLM(), jobs), jobs, tts=synth)), store


def test_status_is_public_and_describes_the_voice(tmp_path):
    client, _ = make_client(tmp_path, installed=False)
    body = client.get("/voice/status").json()
    assert body["installed"] is False and body["downloading"] is False and "size_mb" in body


def test_speak_returns_wav_and_needs_the_ui_header(tmp_path):
    pytest.importorskip("numpy", reason="needs the voice extra (uv sync --extra voice)")
    client, _ = make_client(tmp_path)
    assert client.post("/speak", json={"text": "oi"}).status_code == 403
    r = client.post("/speak", json={"text": "oi", "speed": "fast"}, headers=UI)
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content[:4] == b"RIFF"
    assert r.headers["cache-control"] == "no-store"


def test_speak_errors(tmp_path):
    client, _ = make_client(tmp_path, installed=False)
    assert client.post("/speak", json={"text": "oi"}, headers=UI).status_code == 409  # voice not downloaded yet
    client, _ = make_client(tmp_path / "b")
    assert client.post("/speak", json={"text": "  "}, headers=UI).status_code == 422
    assert client.post("/speak", json={"text": "oi", "speed": "warp"}, headers=UI).status_code == 422


def test_download_and_remove_need_the_ui_header_and_work(tmp_path):
    client, store = make_client(tmp_path, installed=False)
    assert client.post("/voice/download").status_code == 403
    assert client.delete("/voice").status_code == 403
    r = client.post("/voice/download", headers=UI)
    assert r.status_code == 200
    for _ in range(100):
        if client.get("/voice/status").json()["installed"]:
            break
        import time

        time.sleep(0.02)
    assert client.get("/voice/status").json()["installed"] is True
    assert client.delete("/voice", headers=UI).json()["installed"] is False


def test_without_a_synthesizer_the_routes_say_so():
    jobs = JobStore(":memory:")
    client = TestClient(create_app(Engine(FakeGate(), FakeLLM(), jobs), jobs))
    assert client.get("/voice/status").status_code == 503
    assert client.post("/speak", json={"text": "oi"}, headers=UI).status_code == 503
