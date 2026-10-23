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
