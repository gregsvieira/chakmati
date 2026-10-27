import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class PruneConfig:
    threshold: float = 0.5
    max_keep: int = 4
    min_keep: int = 1


def prune(parts: Sequence[str], scores: Sequence[float], cfg: PruneConfig) -> list[str]:
    if len(parts) != len(scores):
        raise ValueError("parts and scores must have the same length")
    by_score = sorted(range(len(parts)), key=lambda i: -scores[i])  # stable on ties
    chosen = [i for i in by_score if scores[i] >= cfg.threshold][: cfg.max_keep]
    if len(chosen) < cfg.min_keep:
        chosen = by_score[: cfg.min_keep]
    return [parts[i] for i in sorted(chosen)]


def prune_by_rank(
    parts: Sequence[str],
    scores: Sequence[float],
    keep_fraction: float = 0.5,
    min_keep: int = 1,
    max_keep: int | None = None,
) -> list[str]:
    """Keep the top `keep_fraction` of parts by score, regardless of the score scale."""
    if len(parts) != len(scores):
        raise ValueError("parts and scores must have the same length")
    n = len(parts)
    if n == 0:
        return []
    k = max(min_keep, math.ceil(n * keep_fraction))
    if max_keep is not None:
        k = min(k, max_keep)
    k = min(k, n)
    by_score = sorted(range(n), key=lambda i: -scores[i])  # stable on ties
    return [parts[i] for i in sorted(by_score[:k])]


def prune_relative_to_best(
    parts: Sequence[str], scores: Sequence[float], ratio: float = 0.5
) -> list[str]:
    """Keep parts whose score is at least `ratio` times the best score (the best always stays)."""
    if len(parts) != len(scores):
        raise ValueError("parts and scores must have the same length")
    if not parts:
        return []
    cutoff = ratio * max(scores)
    return [p for p, s in zip(parts, scores, strict=True) if s >= cutoff]
