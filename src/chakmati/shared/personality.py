"""Regional Brazilian personalities ("Carioca", "Paulista", "Gaúcho"...), done in code after the model has answered.

Why not a pre-prompt: it costs tokens on every call, a 0.8B-4B model overdoes it or drops it, and it can bend the facts (a date, a number).
Here the model's text is never touched: a short opening exclamation and/or a closing vocative is added around it, so the answer stays right,
the cost is a few microseconds, and it works the same with any model.

    "Hoje é 6 de novembro."  (gaucho)  ->  "Mas bah, tchê! Hoje é 6 de novembro, bagual velho!"

Only short, single-paragraph chat answers get it: lists, code, links, plans and approvals are left exactly as they are."""

import random
import re
from dataclasses import dataclass

DEFAULT = "padrao"
MAX_WORDS = 45  # past this an answer is a text, not a quip: it is left alone
OPENER_CHANCE = 0.75
CLOSER_CHANCE = 0.75  # when both rolls fail one of them is forced: a personality that is chosen is always heard


@dataclass(frozen=True)
class Personality:
    id: str
    name: str
    openers: tuple[str, ...] = ()  # exclamations that fit any answer (never a judgement of it)
    closers: tuple[str, ...] = ()  # vocatives that end the sentence ("..., tchê!")


PERSONALITIES: tuple[Personality, ...] = (
    Personality(DEFAULT, "Padrão"),
    Personality("carioca", "Carioca", ("E aí, mermão!", "Fala, parceiro!", "Beleza, meu irmão!", "Opa, tranquilo!"), ("mermão", "parceiro", "meu irmão", "tá ligado")),
    Personality("paulista", "Paulista", ("Fala, mano!", "E aí, meu!", "Salve, mano!", "Beleza, meu!"), ("mano", "meu", "truta", "meu chapa")),
    Personality("gaucho", "Gaúcho", ("Mas bah, tchê!", "Bah, tchê!", "Olha só, tchê!", "Bah, guri!"), ("bagual velho", "tchê", "guri", "meu velho")),
    Personality("nordestino", "Nordestino", ("Oxente!", "Vixe!", "Eita, visse!", "Ôxe, meu rei!"), ("meu rei", "visse", "cabra bom", "meu fi")),
    Personality("mineiro", "Mineiro", ("Uai!", "Ô sô!", "Nossa, sô!", "Ô trem bão!"), ("sô", "uai", "gente", "meu povo")),
)
_BY_ID = {p.id: p for p in PERSONALITIES}

_ENDING = re.compile(r"[.!?…]+$")
_BLOCKS = ("```", "[[action:", "http://", "https://", "www.")


def valid(personality_id: str) -> bool:
    return personality_id in _BY_ID


def normalize(personality_id: str | None) -> str:
    """The id when it is a known personality, otherwise the default (an unknown value in the environment never breaks the engine)."""
    return personality_id if personality_id in _BY_ID else DEFAULT


def options() -> list[dict[str, str]]:
    return [{"id": p.id, "name": p.name} for p in PERSONALITIES]


def eligible(text: str) -> bool:
    """A short, single-paragraph answer with nothing that must stay exact (code, links, a pending approval)."""
    body = text.strip()
    return bool(body) and "\n" not in body and len(body.split()) <= MAX_WORDS and not any(mark in body for mark in _BLOCKS)


def flavor(text: str, personality_id: str, rng: random.Random | None = None) -> str:
    """`text` with the personality's opening and/or closing added; `text` itself when there is nothing to add or it must stay as it is."""
    personality = _BY_ID.get(personality_id)
    if personality is None or not personality.openers or not eligible(text):
        return text
    rng = rng or random
    body = text.strip()
    ending = _ENDING.search(body)
    stem = body[: ending.start()] if ending else body
    can_close = not (ending and ending.group().endswith("?")) and bool(stem) and stem[-1] not in ",;:"  # "Qual arquivo?" and "Segue:" take no vocative
    opener = rng.random() < OPENER_CHANCE
    closer = can_close and rng.random() < CLOSER_CHANCE
    if not opener and not closer:
        opener, closer = (True, False) if not can_close or rng.random() < 0.5 else (False, True)
    if closer:
        body = f"{stem}, {rng.choice(personality.closers)}!"
    if opener:
        body = f"{rng.choice(personality.openers)} {body}"
    return body
