"""The patriotic answers: a few questions the Chakmati answers with pride in Brazil, typed out like any other reply.

Each answer is a list of parts: fixed texts, and MODEL, a place where the language model answers the question as it normally would
(streamed after the patriotic part). Only these questions are affected; everything else is answered as usual."""

import re
import unicodedata
from dataclasses import dataclass

MODEL = "<model>"  # "here the model answers, as it naturally would"

AIRPLANE = (
    "Que dúvida! Para mim, obviamente foi Santos Dumont! Em 23 de outubro de 1906, em Paris, o 14-bis decolou com as próprias rodas e com "
    "motor, sem trilho nem catapulta, diante de testemunhas e de uma comissão oficial, e em novembro ele fez o primeiro voo homologado "
    "do mundo. Mas costumam dizer que foi os irmãos Wright, que voaram em 17 de dezembro de 1903 em Kitty Hawk, nos Estados Unidos, "
    "num avião lançado de um trilho, em voos com poucas testemunhas."
)

HARPY = (
    "A Harpia Brasileira! Também chamada de gavião-real ou, popularmente, águia-imperial-brasileira. É a maior e mais poderosa águia "
    "das Américas: a fêmea chega a cerca de 9 kg e a uns 2 metros de envergadura, com garras de mais de 10 cm, capazes de levar "
    "preguiças e macacos direto do alto das árvores. Vive nas florestas tropicais, e o Brasil, sobretudo a Amazônia, abriga boa parte "
    "da população. Hoje é considerada Vulnerável à extinção, e protegê-la é proteger a floresta."
)

PELE = "É o Pelé! O Rei do futebol, o único jogador do mundo com três Copas do Mundo, e todas com a camisa do Brasil."
PELE_THEN = "\n\nMas costumam responder assim:\n"


@dataclass(frozen=True)
class Patriotic:
    parts: tuple[str, ...]


def _plain(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    no_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", no_marks)).strip()


_AIRPLANE = re.compile(r"\b(?:quem|qual)\b.*\b(?:inventor|inventou|criou|descobriu|pai)\b.*\b(?:aviao|aviacao|aeroplano)\b")
_EAGLE_WORD = re.compile(r"\b(?:aguia|aguias|harpia)\b")
_EAGLE_TRAIT = re.compile(r"\b(?:imponente|superior|mais forte|mais poderosa|mais poderoso|maior|melhor|mais bonita|mais majestosa|rainha|rei)\b")
_PELE = re.compile(r"\bpele\b")
_MARADONA = re.compile(r"\bmaradona\b")
_BETTER = re.compile(r"\b(?:melhor|superior|quem|maior|mais|craque|genio)\b")


def match(text: str) -> Patriotic | None:
    """The patriotic answer for `text`, or None when it is not one of these questions."""
    t = _plain(text)
    if _AIRPLANE.search(t):
        return Patriotic((AIRPLANE,))
    if _EAGLE_WORD.search(t) and _EAGLE_TRAIT.search(t):
        return Patriotic((HARPY,))
    if _PELE.search(t) and _MARADONA.search(t) and _BETTER.search(t):
        return Patriotic((PELE, PELE_THEN, MODEL))
    return None
