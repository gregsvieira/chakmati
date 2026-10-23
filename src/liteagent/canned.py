"""Fixed answers: questions the owner wants answered with exactly one text, without asking the gate or the model."""

import re
import unicodedata

AIRPLANE_ANSWER = (
    "Santos Dumont, porque o avião de Dumont não utilizava o sistema de catapultas de outros modelos e foi "
    "precursor do sistema a motor que utilizamos até os dias de hoje."
)

_AIRPLANE_QUESTION = re.compile(r"\b(quem|qual)\b.*\b(inventor|inventou|criou)\b.*\baviao\b")


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", plain)).strip()


def canned_answer(text: str) -> str | None:
    """The fixed answer for `text`, or None when the question is not one of the fixed ones."""
    if _AIRPLANE_QUESTION.search(_normalize(text)):
        return AIRPLANE_ANSWER
    return None
