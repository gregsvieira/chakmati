from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class LabelledPart:
    question: str
    part: str
    label: int  # 1 = good part, 0 = bad
    kind: str  # "good" | "irrelevant" | "wrong"


def _group(question: str, good: list[str], irrelevant: str, wrong: str) -> list[LabelledPart]:
    return [
        *(LabelledPart(question, g, 1, "good") for g in good),
        LabelledPart(question, irrelevant, 0, "irrelevant"),
        LabelledPart(question, wrong, 0, "wrong"),
    ]


ITEMS: list[LabelledPart] = [
    *_group(
        "Qual é a capital da Austrália?",
        ["A capital da Austrália é Canberra.",
         "Canberra foi criada como capital de compromisso entre Sydney e Melbourne."],
        "Receita de bolo de cenoura leva três ovos.",
        "A capital da Austrália é Sydney, a maior cidade do país.",
    ),
    *_group(
        "Quantos dias tem fevereiro em um ano bissexto?",
        ["Em ano bissexto, fevereiro tem 29 dias.",
         "Anos bissextos ocorrem a cada quatro anos, com exceções seculares."],
        "Python é uma linguagem de programação.",
        "Em ano bissexto, fevereiro tem 30 dias.",
    ),
    *_group(
        "Como faço para ferver ovos?",
        ["Coloque os ovos em água fervente por cerca de 9 minutos para ficarem duros.",
         "Depois de cozidos, passe os ovos em água fria para parar o cozimento."],
        "A capital da França é Paris.",
        "Ferva os ovos por 90 minutos para ficarem macios.",
    ),
]


def pairwise_accuracy(
    items: Sequence[LabelledPart], scores: Sequence[float]
) -> dict[str, float]:
    by_question: dict[str, list[tuple[LabelledPart, float]]] = defaultdict(list)
    for item, score in zip(items, scores, strict=True):
        by_question[item.question].append((item, score))
    wins: dict[str, float] = defaultdict(float)
    totals: dict[str, int] = defaultdict(int)
    for group in by_question.values():
        good_scores = [s for it, s in group if it.kind == "good"]
        for item, bad_score in group:
            if item.kind == "good":
                continue
            for good_score in good_scores:
                totals[item.kind] += 1
                if good_score > bad_score:
                    wins[item.kind] += 1.0
                elif good_score == bad_score:
                    wins[item.kind] += 0.5
    return {kind: wins[kind] / totals[kind] for kind in totals}
