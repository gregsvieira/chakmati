from collections import defaultdict
from collections.abc import Callable, Sequence
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


ITEMS_EXTRA: list[LabelledPart] = [
    *_group(
        "Qual é a maior cidade do Brasil?",
        ["A maior cidade do Brasil é São Paulo.",
         "São Paulo tem mais de 11 milhões de habitantes no município."],
        "A fotossíntese ocorre nos cloroplastos.",
        "A maior cidade do Brasil é o Rio de Janeiro.",
    ),
    *_group(
        "Quanto é 15% de 200?",
        ["15% de 200 é 30.", "Calcula-se multiplicando 200 por 0,15."],
        "O Rio Amazonas é o mais volumoso do mundo.",
        "15% de 200 é 15.",
    ),
    *_group(
        "Quem escreveu Dom Casmurro?",
        ["Dom Casmurro foi escrito por Machado de Assis.",
         "O livro foi publicado em 1899."],
        "A água ferve a 100 graus ao nível do mar.",
        "Dom Casmurro foi escrito por José de Alencar.",
    ),
    *_group(
        "Como reiniciar um roteador?",
        ["Desligue o roteador da tomada por cerca de 30 segundos.",
         "Religue-o e aguarde as luzes estabilizarem."],
        "O Sol é uma estrela de tamanho médio.",
        "Para reiniciar um roteador, mergulhe-o em água por 10 minutos.",
    ),
    *_group(
        "Por que o céu é azul?",
        ["A luz azul é espalhada mais que as outras cores pela atmosfera.",
         "Esse fenômeno se chama espalhamento de Rayleigh."],
        "Canberra é a capital da Austrália.",
        "O céu é azul porque reflete a cor do oceano.",
    ),
]

ALL_ITEMS: list[LabelledPart] = ITEMS + ITEMS_EXTRA


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


Strategy = Callable[[Sequence[str], Sequence[float]], list[str]]


def strategy_report(
    items: Sequence[LabelledPart],
    scores: Sequence[float],
    strategies: dict[str, Strategy],
) -> dict[str, dict[str, float]]:
    """Apply each pruning strategy per question; report how many good parts survive
    and how many irrelevant / wrong parts are dropped."""
    by_question: dict[str, list[tuple[LabelledPart, float]]] = defaultdict(list)
    for item, score in zip(items, scores, strict=True):
        by_question[item.question].append((item, score))
    report: dict[str, dict[str, float]] = {}
    for name, strategy in strategies.items():
        kept = {"good": 0, "irrelevant": 0, "wrong": 0}
        total = {"good": 0, "irrelevant": 0, "wrong": 0}
        for group in by_question.values():
            parts = [it.part for it, _ in group]
            survivors = set(strategy(parts, [s for _, s in group]))
            for it, _ in group:
                total[it.kind] += 1
                kept[it.kind] += it.part in survivors
        report[name] = {
            "good_kept": kept["good"] / total["good"],
            "irrelevant_dropped": 1 - kept["irrelevant"] / total["irrelevant"],
            "wrong_dropped": 1 - kept["wrong"] / total["wrong"],
        }
    return report
