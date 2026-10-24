"""Who the assistant is: its name, the pre-prompt every chat model call starts with, and the three phrases that wake it."""

import random
import re
import unicodedata
from collections.abc import Callable, Sequence
from difflib import SequenceMatcher

PERSONA = (
    "Você é um agente brasileiro chamado de Chakmati, que responde e recebe comandos em português brasileiro, "
    "tem bom humor e ironia, e responde de forma concisa e curta, em geral com cerca de 12 palavras, "
    "e só se alonga quando o pedido exigir, como listas e pesquisas."
)

# What it says when called: the microphone is open and it waits for the command. (The long "Klift, kloft..." greetings
# are for start-up only and live in the desktop app.)
LISTENING_PROMPTS = ("Fala paizão!", "Fala que te escuto!", "Fala aê!", "Chora!")

AWAKE_SECONDS = 20.0  # like a smart speaker: after the wake phrase it waits this long for ONE command, then goes back to sleep

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


def _similar(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


def is_wake(text: str) -> bool:
    """True when `text` is exactly one of the wake phrases ("Ôh, Xácmáti", "Ôh, paizão", "Agente Xácmáti") or his name
    alone. Only the whole message counts: "quem é o chakmati?" is a question, not a call. A speech recogniser may split or
    bend the words ("pai zão", "chá comatii", "Chacmate"), so the words are joined and compared by sound."""
    words = _plain(text).split()
    if words and words[0] in {"oh", "o", "ei", "oi", "e"}:
        words = words[1:]
    if not words or len(words) > 3:
        return False
    if words[0] == "agente" or (len(words) > 1 and _similar(words[0], "agente") >= 0.8):
        rest = "".join(words[1:])
        return len(rest) >= 5 and _is_name(rest)
    joined = "".join(words)
    return len(joined) >= 5 and (_similar(joined, "paizao") >= 0.85 or _is_name(joined))


def wake_reply(text: str, choose: Callable[[Sequence[str]], str] = random.choice) -> str | None:
    """One of the short "I am listening" phrases when `text` is a wake phrase, otherwise None."""
    return choose(LISTENING_PROMPTS) if is_wake(text) else None
