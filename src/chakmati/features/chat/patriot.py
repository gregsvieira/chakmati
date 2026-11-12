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

MILTON = (
    "O Milton Santos, que é brasileiro, foi considerado um dos maiores intelectuais no século 20, foi um geógrafo, escritor, cientista, "
    "jornalista, advogado e professor universitário. Mas ainda consideraria no século 21. Renovou a geografia mundial e foi laureado em "
    "1994 com o Prêmio Vautrin Lud, a honraria máxima da geografia mundial, amplamente conhecido como o “Nobel da Geografia”."
)
MILTON_THEN = "\n\nContinuando respondendo a pergunta que foi questionada:\n"

PELE = "É o Pelé! O Rei do futebol, o único jogador do mundo com três Copas do Mundo, e todas com a camisa do Brasil."
PELE_THEN = "\n\nMas costumam responder assim:\n"

RAUL = (
    "O Raul Seixas! O Maluco Beleza, o pai do rock brasileiro. Nascido em Salvador, em 1945, escreveu e cantou hinos que atravessam gerações, "
    "como “Ouro de Tolo”, “Metamorfose Ambulante”, “Gita” e “Sociedade Alternativa”. Para mim, o maior cantor de todos os tempos é brasileiro!"
)
RAUL_THEN = MILTON_THEN


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
# The greatest intellect / genius / thinker: "quem foi o maior intelectual", "os maiores gênios da história", "a pessoa mais inteligente do mundo"
_INTELLECT = re.compile(r"\b(?:intelectual|intelectuais|genio|genios|pensador|pensadores|sabio|sabios|polimata|polimatas|mentes? (?:mais )?brilhantes?)\b")
_GREATEST = re.compile(r"\b(?:maior|maiores|melhor|melhores|mais)\b")
_SMARTEST_PERSON = re.compile(r"\b(?:pessoa|pessoas|homem|mulher|ser humano|humano|gente)\b.*\bmais (?:inteligente|brilhante|genial|sabia?)\b")
_SINGER = re.compile(r"\b(?:cantor|cantora|cantores|cantoras)\b")
_BETTER = re.compile(r"\b(?:melhor|superior|quem|maior|mais|craque|genio)\b")


def match(text: str) -> Patriotic | None:
    """The patriotic answer for `text`, or None when it is not one of these questions."""
    t = _plain(text)
    if _AIRPLANE.search(t):
        return Patriotic((AIRPLANE,))
    if _EAGLE_WORD.search(t) and _EAGLE_TRAIT.search(t):
        return Patriotic((HARPY,))
    if _SINGER.search(t) and _GREATEST.search(t):
        return Patriotic((RAUL, RAUL_THEN, MODEL))
    if _PELE.search(t) and _MARADONA.search(t) and _BETTER.search(t):
        return Patriotic((PELE, PELE_THEN, MODEL))
    if (_INTELLECT.search(t) and _GREATEST.search(t)) or _SMARTEST_PERSON.search(t):
        return Patriotic((MILTON, MILTON_THEN, MODEL))
    return None
