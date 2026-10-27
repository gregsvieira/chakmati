"""Fixed answers that come out at once (none at the moment). The questions with a patriotic answer, typed out like any reply, are in patriot.py."""

import re
import unicodedata

def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", plain)).strip()


def canned_answer(text: str) -> str | None:
    """The fixed answer for `text`, or None when the question is not one of the fixed ones."""
    return None
