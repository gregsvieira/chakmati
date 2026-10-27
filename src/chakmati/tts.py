"""Enhanced voice: a small neural Portuguese (Brazil) voice, Piper "jeff", that runs on the CPU of the computer.

It is optional. The app starts with the voice of the operating system; when the person turns the enhanced voice on, the
model (about 63 MB) is downloaded once from the official Piper voices repository, checked against its published size
and SHA-256, and only then used. Nothing is sent anywhere to speak: the text stays on this computer.
"""

import asyncio
import hashlib
import io
import os
import threading
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from chakmati.extras import missing_message

MAX_TEXT = 600
SPEEDS = {"normal": 1.0, "fast": 0.85}  # Piper's length_scale: smaller is faster
_ALLOWED_HOST = "huggingface.co"
_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/jeff/medium"


class VoiceError(Exception):
    pass


@dataclass(frozen=True)
class VoiceFile:
    name: str
    url: str
    size: int
    sha256: str


VOICE_FILES = (
    VoiceFile("pt_BR-jeff-medium.onnx", f"{_BASE}/pt_BR-jeff-medium.onnx?download=true", 62950044,
              "3a6f4c46355813c2b7bbc4d16b6d13d60ed72074b952a393baace82a7d0c94b5"),
    VoiceFile("pt_BR-jeff-medium.onnx.json", f"{_BASE}/pt_BR-jeff-medium.onnx.json?download=true", 5041,
              "7bf8145b572b36806f5ce0f1d3322b6711975bc7d0473e8d36fced4a9ec0030d"),
)


def _default_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=httpx.Timeout(30.0, read=60.0), follow_redirects=True)


class VoiceStore:
    """The voice files on disk, and downloading them."""

    def __init__(self, directory, files: tuple[VoiceFile, ...] = VOICE_FILES,
                 client_factory: Callable[[], httpx.AsyncClient] = _default_client):
        for f in files:
            parts = urlsplit(f.url)
            if parts.scheme != "https":
                raise VoiceError("voice downloads must use https")
            if parts.hostname != _ALLOWED_HOST:
                raise VoiceError(f"voice downloads are only allowed from {_ALLOWED_HOST} (host {parts.hostname!r})")
        self._dir = Path(directory)
        self._files = files
        self._client_factory = client_factory
        self._lock = asyncio.Lock()
        self._downloading = False
        self._progress = 0.0
        self._error: str | None = None
        self.total_bytes = sum(f.size for f in files)

    @property
    def model_path(self) -> str:
        return str(self._dir / self._files[0].name)

    def installed(self) -> bool:
        return all((self._dir / f.name).is_file() and (self._dir / f.name).stat().st_size == f.size for f in self._files)

    def status(self) -> dict:
        return {
            "installed": self.installed(), "downloading": self._downloading,
            "progress": round(self._progress, 3), "error": self._error,
            "size_mb": round(self.total_bytes / 1_000_000, 1),
        }

    def _set_progress(self, done: int, total: int) -> None:
        self._progress = done / total if total else 0.0

    async def download(self) -> None:
        """Download and verify the voice. Never raises: failures are reported in `status()["error"]`."""
        if self._downloading:
            return
        async with self._lock:
            if self.installed():
                self._error = None
                return
            self._downloading, self._error, self._progress = True, None, 0.0
            self._dir.mkdir(parents=True, exist_ok=True)
            try:
                done = 0
                async with self._client_factory() as client:
                    for f in self._files:
                        done = await self._fetch(client, f, done)
                self._progress = 1.0
            except VoiceError as exc:
                self._error = str(exc)
            except httpx.HTTPError as exc:
                self._error = f"could not download the voice: {exc}"
            finally:
                self._downloading = False

    async def _fetch(self, client: httpx.AsyncClient, f: VoiceFile, done: int) -> int:
        part = self._dir / (f.name + ".part")
        digest = hashlib.sha256()
        size = 0
        try:
            async with client.stream("GET", f.url) as response:
                if response.status_code != 200:
                    raise VoiceError(f"the voice server answered {response.status_code}")
                with part.open("wb") as out:
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > f.size:
                            raise VoiceError("the downloaded file is larger than expected (size)")
                        digest.update(chunk)
                        out.write(chunk)
                        self._set_progress(done + size, self.total_bytes)
            if size != f.size:
                raise VoiceError("the downloaded file has the wrong size")
            if digest.hexdigest() != f.sha256:
                raise VoiceError("the downloaded file does not match its published hash")
            os.replace(part, self._dir / f.name)
        finally:
            part.unlink(missing_ok=True)
        return done + size

    def remove(self) -> None:
        for f in self._files:
            (self._dir / f.name).unlink(missing_ok=True)
            (self._dir / (f.name + ".part")).unlink(missing_ok=True)
        self._error, self._progress = None, 0.0


def _load_piper(model_path: str):
    try:
        from piper import PiperVoice
    except ImportError:
        raise VoiceError(missing_message("voice", "the enhanced voice")) from None

    return PiperVoice.load(model_path)


class VoiceSynth:
    def __init__(self, store: VoiceStore, loader: Callable[[str], object] = _load_piper):
        self.store = store
        self._loader = loader
        self._voice = None
        self._lock = threading.Lock()  # one voice, one sentence at a time

    def synthesize(self, text: str, speed: str = "normal") -> bytes:
        """The text as a 16-bit mono WAV file."""
        clean = (text or "").strip()
        if not clean:
            raise VoiceError("the text is empty")
        if len(clean) > MAX_TEXT:
            raise VoiceError(f"the text is too long (more than {MAX_TEXT} characters)")
        if speed not in SPEEDS:
            raise VoiceError(f"unknown speed {speed!r}")
        if not self.store.installed():
            raise VoiceError("the enhanced voice is not installed")
        with self._lock:
            if self._voice is None:
                self._voice = self._loader(self.store.model_path)
            voice = self._voice
            config = None
            if SPEEDS[speed] != 1.0:
                from piper import SynthesisConfig

                config = SynthesisConfig(length_scale=SPEEDS[speed])
            import numpy as np

            chunks = [np.asarray(c.audio_float_array, dtype=np.float32) for c in voice.synthesize(clean, syn_config=config)]  # type: ignore[attr-defined]
            rate = voice.config.sample_rate  # type: ignore[attr-defined]
        if not chunks:
            raise VoiceError("the voice produced no sound")
        pcm = (np.clip(np.concatenate(chunks), -1, 1) * 32767).astype(np.int16)
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(pcm.tobytes())
        return buffer.getvalue()
