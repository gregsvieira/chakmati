"""Who the assistant is: its name, the pre-prompt every chat model call starts with, and the three phrases that wake it."""

import re
import unicodedata
from difflib import SequenceMatcher

PERSONA = "Você é um agente brasileiro chamado de Chakmati, que responde e recebe comandos em português brasileiro."

OPEN_DOOR = "Klift, kloft, still, a porta se abriu!"
PAIZAO = "Klift, still, kloft! fala fióti."
AGENTE = "Klift, kloft, stão! fala paizão!"
GREETINGS = {"name": OPEN_DOOR, "paizao": PAIZAO, "agente": AGENTE}

AWAKE_SECONDS = 120.0  # how long it keeps waiting for the command after a wake phrase

_NAME = "xacmati"


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    no_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", no_marks)).strip()


def _is_name(word: str) -> bool:
    """His name as written, or as a speech recogniser may hear it (Chakmati, Xacmati, Shakmati, Chaquemati...):
    the same sounds are spelled the same way first, then the word has to be very close to the name."""
    sound = re.sub(r"qu|k|c", "c", re.sub(r"ch|sh|x", "x", word))
    return SequenceMatcher(None, sound, _NAME).ratio() >= 0.8


def wake_reply(text: str) -> str | None:
    """The fixed greeting when `text` is exactly one of the wake phrases, otherwise None. Only the whole message counts:
    "quem é o chakmati?" is a question, not a call."""
    words = _plain(text).split()
    if not words or len(words) > 3:
        return None
    if words[0] in {"oh", "o", "ei", "oi", "e"}:
        words = words[1:]
    if len(words) == 1:
        if words[0] == "paizao":
            return PAIZAO
        if _is_name(words[0]):
            return OPEN_DOOR
    if len(words) == 2 and words[0] == "agente" and _is_name(words[1]):
        return AGENTE
    return None
