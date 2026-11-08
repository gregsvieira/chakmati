"""Local speech recognition (faster-whisper) so the person can talk to the assistant. Nothing leaves the computer.

The model is loaded (and downloaded, about 140 MB for "base", the first time only) on the first request, not at start-up,
so people who never use the microphone pay nothing.
"""

import io
import re
import threading
from collections.abc import Callable

from chakmati.shared.extras import missing_message

MAX_AUDIO_BYTES = 20 * 1024 * 1024
# Words the recogniser would otherwise get wrong: the assistant's name and the Alexa. Kept SHORT on purpose: a long prompt of wake phrases leaks into the
# text on weak audio ("Ôh, Xácmáti. Ôh, Xácmáti. Ôh, Xácmáti..."), which wakes the assistant by itself and fills the answers with its own name.
VOCABULARY = "Chakmati. Xácmáti. Alexa."
DEFAULT_LANGUAGE = "pt"  # the app is Portuguese: left to guess, the model took short commands for English ("Toca Raul Seixas na Alexa" -> "Hocus-Hocus all seats...")
NO_SPEECH = 0.6  # a segment the model itself thinks is not speech, and is unsure of, is dropped
_REPEATED = 3  # the same sentence this many times in a row is a loop of the model, not a person


class TranscribeError(Exception):
    pass


_SENTENCE = re.compile(r"(?<=[.!?…])\s+")
_FOREIGN = re.compile(r"[\u0370-\u03ff\u0400-\u04ff\u0590-\u06ff\u0e00-\u0e7f\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")  # Greek, Cyrillic, Hebrew, Arabic, Thai, kana, CJK, Hangul


def clean(text: str, language: str = DEFAULT_LANGUAGE) -> str:
    """What the recogniser invents from noise, silence or a prompt it is echoing is dropped: text in a script the person does not speak ("玉玉。"), and a sentence
    repeated in a loop. A fixed language keeps the first check meaningful; "auto" lets any script through."""
    out = text.strip()
    if not out:
        return ""
    if language != "auto" and _FOREIGN.search(out):
        return ""
    sentences = [x.strip() for x in _SENTENCE.split(out) if x.strip()]
    run = 1
    for a, b in zip(sentences, sentences[1:]):
        run = run + 1 if a.lower() == b.lower() else 1
        if run >= _REPEATED:
            return ""
    return out

def _load_whisper(name: str):
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise TranscribeError(missing_message("listen", "speech recognition")) from None
    return WhisperModel(name, device="cpu", compute_type="int8")


class SpeechToText:
    def __init__(self, model_name: str = "base", loader: Callable[[str], object] = _load_whisper, language: str = DEFAULT_LANGUAGE):
        self._name = model_name
        self._language = language or DEFAULT_LANGUAGE
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
                segments, info = self._model.transcribe(  # type: ignore[attr-defined]
                    io.BytesIO(audio), beam_size=3, vad_filter=True, initial_prompt=VOCABULARY, language=None if self._language == "auto" else self._language,
                    condition_on_previous_text=False, temperature=0,
                )
                kept = [s for s in segments if not (getattr(s, "no_speech_prob", 0.0) > NO_SPEECH and getattr(s, "avg_logprob", 0.0) < -1.0)]
                text = clean(" ".join(s.text.strip() for s in kept), self._language)
            except TranscribeError:
                raise
            except Exception as exc:
                raise TranscribeError(f"could not transcribe the recording: {exc}") from None
        return text, getattr(info, "language", "") or ("" if self._language == "auto" else self._language)
