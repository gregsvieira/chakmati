from collections.abc import Sequence

from chakmati.loop.scorer import PartScorer
from chakmati.research.search import SearchResult


def filter_results(
    query: str,
    results: Sequence[SearchResult],
    scorer: PartScorer,
    cutoff: float = 0.2,
    min_keep: int = 3,
) -> list[SearchResult]:
    if not results:
        return []
    scores = scorer.score(query, [r.text for r in results])
    chosen = [i for i, s in enumerate(scores) if s >= cutoff]
    if len(chosen) < min_keep:
        by_score = sorted(range(len(results)), key=lambda i: -scores[i])
        chosen = by_score[:min_keep]
    return [results[i] for i in sorted(chosen)]


def rank_passages(
    query: str, passages: Sequence[str], scorer: PartScorer, top_k: int = 4
) -> list[str]:
    if not passages:
        return []
    scores = scorer.score(query, list(passages))
    best = sorted(range(len(passages)), key=lambda i: -scores[i])[:top_k]
    return [passages[i] for i in sorted(best)]
