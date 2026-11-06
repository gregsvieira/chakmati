"""Regional Brazilian personalities ("Carioca", "Paulista", "Gaúcho"...), done in code after the model has answered.

Why not a pre-prompt: it costs tokens on every call, a 0.8B-4B model overdoes it or drops it, and it can bend the facts (a date, a number).
Here the model's text is never touched: a short opening exclamation and/or a closing vocative is added around it, so the answer stays right,
the cost is a few microseconds, and it works the same with any model.

    "Hoje é 6 de novembro."  (gaucho, ele/dele)  ->  "Mas bah, tchê! Hoje é 6 de novembro, bagual velho!"

The vocatives agree with the person's pronouns (shared/pronouns.py): "guri" for ele/dele, "guria" for ela/dela, "amigue" for elu/delu, and only the words that
fit anyone ("tchê") when they did not say. Nobody is misgendered by a word the code adds.

Only short, single-paragraph chat answers get it: lists, code, links, plans and approvals are left exactly as they are."""

import random
import re
from dataclasses import dataclass

DEFAULT = "padrao"
MAX_WORDS = 45  # past this an answer is a text, not a quip: it is left alone
OPENER_CHANCE = 0.75
CLOSER_CHANCE = 0.75  # when both rolls fail one of them is forced: a personality that is chosen is always heard


@dataclass(frozen=True)
class Lines:
    """Phrases by who is being addressed. `shared` fits anyone (and is all that is used when the person did not say their pronouns);
    `ele`, `ela` and `elu` add the words that agree with those pronouns ("guri" / "guria" / "amigue")."""

    shared: tuple[str, ...] = ()
    ele: tuple[str, ...] = ()
    ela: tuple[str, ...] = ()
    elu: tuple[str, ...] = ()

    def for_pronouns(self, pronouns_id: str) -> tuple[str, ...]:
        return getattr(self, pronouns_id, ()) + self.shared if pronouns_id in {"ele", "ela", "elu"} else self.shared


@dataclass(frozen=True)
class Personality:
    id: str
    name: str
    openers: Lines = Lines()  # exclamations that fit any answer (never a judgement of it)
    closers: Lines = Lines()  # vocatives that end the sentence ("..., tchê!")
    listening: Lines = Lines()  # what it says when called by its name: the microphone is open and it waits for the command (empty = the standard ones)


PERSONALITIES: tuple[Personality, ...] = (
    Personality(DEFAULT, "Padrão"),
    Personality(
        "carioca", "Carioca",
        Lines(("E aí!", "Opa, fala aí!", "Salve!"), ("E aí, mermão!", "Fala, parceiro!", "Beleza, meu irmão!"), ("E aí, mana!", "Fala, parceira!", "Beleza, minha irmã!"), ("E aí, amigue!",)),
        Lines(("tá ligado", "parça"), ("mermão", "parceiro", "meu irmão"), ("mana", "parceira", "minha irmã"), ("amigue",)),
        Lines(("Fala aí, que eu tô ouvindo!", "Manda aí, tô na escuta!"), ("E aí, parceiro, pode falar!", "Diz aí, meu irmão!"), ("E aí, parceira, pode falar!", "Diz aí, minha irmã!"), ("E aí, amigue, pode falar!",)),
    ),
    Personality(
        "paulista", "Paulista",
        Lines(("Salve!", "Fala aí!", "Beleza!"), ("Fala, mano!", "E aí, meu!"), ("Fala, mana!", "E aí, mina!"), ("E aí, amigue!",)),
        Lines(("truta", "parça"), ("mano", "meu", "meu chapa"), ("mana", "mina", "minha chapa"), ("amigue",)),
        Lines(("Fala aí, tô ouvindo!", "Manda a visão!"), ("Pode falar, mano!", "Fala, meu!"), ("Pode falar, mana!", "Fala, mina!"), ("Pode falar, amigue!",)),
    ),
    Personality(
        "gaucho", "Gaúcho",
        Lines(("Mas bah, tchê!", "Bah, tchê!", "Olha só, tchê!"), ("Bah, guri!",), ("Bah, guria!",), ("Bah, amigue!",)),
        Lines(("tchê", "gente boa"), ("bagual velho", "guri", "meu velho"), ("bagual velha", "guria", "minha querida"), ("amigue",)),
        Lines(("Fala, tchê, que te escuto!", "Tô na escuta, tchê!"), ("Bah, pode falar, guri!", "Manda ver, bagual velho!"), ("Bah, pode falar, guria!", "Manda ver, bagual velha!"), ("Bah, pode falar, amigue!",)),
    ),
    Personality(
        "nordestino", "Nordestino",
        Lines(("Oxente!", "Vixe!", "Eita, visse!"), ("Ôxe, meu rei!",), ("Ôxe, minha rainha!",), ("Ôxe, amigue!",)),
        Lines(("visse", "gente boa"), ("meu rei", "cabra bom", "meu fi"), ("minha rainha", "cabra boa", "minha fia"), ("amigue",)),
        Lines(("Oxente, pode falar, visse!", "Tô ouvindo, visse!"), ("Fala, meu rei, tô ouvindo!", "Diz aí, cabra bom!"), ("Fala, minha rainha, tô ouvindo!", "Diz aí, cabra boa!"), ("Fala, amigue, tô ouvindo!",)),
    ),
    Personality(
        "mineiro", "Mineiro",
        Lines(("Uai!", "Ô sô!", "Nossa, sô!", "Ô trem bão!")),
        Lines(("sô", "uai", "gente", "meu povo")),
        Lines(("Fala, sô, que eu tô ouvindo!", "Uai, pode falar!", "Manda o trem, sô!", "Diz aí, uai!")),
    ),
)
_BY_ID = {p.id: p for p in PERSONALITIES}

_ENDING = re.compile(r"[.!?…]+$")
_BLOCKS = ("```", "[[action:", "http://", "https://", "www.")


def valid(personality_id: str) -> bool:
    return personality_id in _BY_ID


def normalize(personality_id: str | None) -> str:
    """The id when it is a known personality, otherwise the default (an unknown value in the environment never breaks the engine)."""
    return personality_id if personality_id in _BY_ID else DEFAULT


def listening_prompts(personality_id: str, pronouns_id: str = "none") -> tuple[str, ...]:
    """The "I am listening" phrases of a personality for these pronouns; empty for the default, which uses the standard ones (shared/persona.py)."""
    personality = _BY_ID.get(personality_id)
    return personality.listening.for_pronouns(pronouns_id) if personality else ()


def options() -> list[dict[str, str]]:
    return [{"id": p.id, "name": p.name} for p in PERSONALITIES]


def eligible(text: str) -> bool:
    """A short, single-paragraph answer with nothing that must stay exact (code, links, a pending approval)."""
    body = text.strip()
    return bool(body) and "\n" not in body and len(body.split()) <= MAX_WORDS and not any(mark in body for mark in _BLOCKS)


def flavor(text: str, personality_id: str, rng: random.Random | None = None, pronouns_id: str = "none") -> str:
    """`text` with the personality's opening and/or closing added; `text` itself when there is nothing to add or it must stay as it is."""
    personality = _BY_ID.get(personality_id)
    openers = personality.openers.for_pronouns(pronouns_id) if personality else ()
    closers = personality.closers.for_pronouns(pronouns_id) if personality else ()
    if not openers or not eligible(text):
        return text
    rng = rng or random
    body = text.strip()
    ending = _ENDING.search(body)
    stem = body[: ending.start()] if ending else body
    can_close = bool(closers) and not (ending and ending.group().endswith("?")) and bool(stem) and stem[-1] not in ",;:"  # "Qual arquivo?" and "Segue:" take no vocative
    opener = rng.random() < OPENER_CHANCE
    closer = can_close and rng.random() < CLOSER_CHANCE
    if not opener and not closer:
        opener, closer = (True, False) if not can_close or rng.random() < 0.5 else (False, True)
    if closer:
        body = f"{stem}, {rng.choice(closers)}!"
    if opener:
        body = f"{rng.choice(openers)} {body}"
    return body
