"""Local speech recognition (faster-whisper) so the person can talk to the assistant. Nothing leaves the computer.

The model is loaded (and downloaded, about 140 MB for "base", the first time only) on the first request, not at start-up,
so people who never use the microphone pay nothing.
"""

import io
import threading
from collections.abc import Callable

MAX_AUDIO_BYTES = 20 * 1024 * 1024


class TranscribeError(Exception):
    pass


def _load_whisper(name: str):
    from faster_whisper import WhisperModel

    return WhisperModel(name, device="cpu", compute_type="int8")


class SpeechToText:
    def __init__(self, model_name: str = "base", loader: Callable[[str], object] = _load_whisper):
        self._name = model_name
        self._loader = loader
        self._model = None
        self._lock = threading.Lock()  # one model, one request at a time

    def transcribe(self, audio: bytes) -> tuple[str, str]:
        """(text, language) for a recording in any format ffmpeg-free PyAV can read (webm/opus, ogg, wav...)."""
        if not audio:
            raise TranscribeError("the recording is empty")
        if len(audio) > MAX_AUDIO_BYTES:
            raise TranscribeError("the recording is too large")
        with self._lock:
            try:
                if self._model is None:
                    self._model = self._loader(self._name)
                segments, info = self._model.transcribe(io.BytesIO(audio), beam_size=1, vad_filter=True)  # type: ignore[attr-defined]
                text = " ".join(s.text.strip() for s in segments).strip()
            except TranscribeError:
                raise
            except Exception as exc:
                raise TranscribeError(f"could not transcribe the recording: {exc}") from None
        return text, getattr(info, "language", "") or ""
