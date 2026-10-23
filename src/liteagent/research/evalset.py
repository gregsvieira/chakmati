from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class LabelledResult:
    query: str
    rank: int
    title: str
    url: str
    snippet: str
    relevant: int
    source: str  # "natural" | "injected"

    @property
    def text(self) -> str:
        return f"{self.title}. {self.snippet}"


def with_injected_negatives(
    items: Sequence[LabelledResult], per_query: int = 3
) -> list[LabelledResult]:
    queries = list(dict.fromkeys(i.query for i in items))
    by_query = {q: [i for i in items if i.query == q] for q in queries}
    out = list(items)
    for n, q in enumerate(queries):
        others = [queries[(n + k) % len(queries)] for k in range(1, len(queries))]
        pool = [r for o in others for r in by_query[o]]
        for r in pool[:per_query]:
            out.append(replace(r, query=q, relevant=0, source="injected"))
    return out


def ranking_metrics(items: Sequence[LabelledResult], scores: Sequence[float]) -> dict[str, float]:
    by_query: dict[str, list[tuple[LabelledResult, float]]] = defaultdict(list)
    for item, score in zip(items, scores, strict=True):
        by_query[item.query].append((item, score))
    wins = 0.0
    pairs = 0
    p3: list[float] = []
    for group in by_query.values():
        good = [s for it, s in group if it.relevant]
        bad = [s for it, s in group if not it.relevant]
        for g in good:
            for b in bad:
                pairs += 1
                wins += 1.0 if g > b else 0.5 if g == b else 0.0
        top = sorted(group, key=lambda p: -p[1])[:3]
        p3.append(sum(it.relevant for it, _ in top) / len(top))
    return {
        "pairwise": wins / pairs if pairs else float("nan"),
        "precision_at_3": sum(p3) / len(p3),
    }
