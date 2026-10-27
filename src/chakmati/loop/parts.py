import json
import re
from collections.abc import Sequence

_PREFIX = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s*")


def parse_parts(text: str) -> list[str]:
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end > start:
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            data = None
        if isinstance(data, list):
            return [s for s in (str(x).strip() for x in data) if s]
    lines = (_PREFIX.sub("", line).strip() for line in text.splitlines())
    return [line for line in lines if line]


def _notes(kept: Sequence[str]) -> str:
    return "\n".join(f"- {p}" for p in kept) or "(none yet)"


def draft_messages(question: str, kept: Sequence[str], k: int = 5) -> list[dict[str, str]]:
    system = (
        "You help answer a question by listing short candidate reasoning steps or "
        f"facts. Reply with ONLY a JSON array of at most {k} short strings, in the "
        "user's language."
    )
    user = f"Question: {question}\nNotes so far:\n{_notes(kept)}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def compose_messages(question: str, kept: Sequence[str]) -> list[dict[str, str]]:
    system = (
        "Answer the question concisely in the user's language, using ONLY the notes. "
        "If the notes are insufficient, say what is missing."
    )
    user = f"Question: {question}\nNotes:\n{_notes(kept)}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]
