import logging
from collections.abc import Sequence
from typing import Any, Protocol

from ..gate import laya_gate
from ..gate.laya_gate import Predictor

log = logging.getLogger(__name__)

PART_QUESTION: dict[str, Any] = {
    "useful": {
        "type": "noul",
        "instructions": (
            "Is this candidate step relevant and useful for answering the question?"
        ),
    }
}


class PartScorer(Protocol):
    def score(self, question: str, parts: Sequence[str]) -> list[float]: ...


class LayaPartScorer:
    def __init__(self, predictor: Predictor | None = None):
        self._predictor = predictor
        self._unavailable = False

    def _resolve(self) -> Predictor | None:
        if self._predictor is None and not self._unavailable:
            try:
                # looked up on the module so tests can monkeypatch it
                self._predictor = laya_gate._default_predictor()
            except ImportError:
                log.warning("laya is not installed; pruning is disabled")
                self._unavailable = True
        return self._predictor

    def score(self, question: str, parts: Sequence[str]) -> list[float]:
        predictor = self._resolve()
        if predictor is None:
            return [1.0] * len(parts)
        scores: list[float] = []
        for part in parts:
            text = f"Question: {question}\nCandidate step: {part}"
            try:
                result = predictor(text, PART_QUESTION)
                scores.append(float(result["answers"]["useful"]["noul"]))
            except Exception:
                log.warning("laya scoring failed for a part; keeping it", exc_info=True)
                scores.append(1.0)
        return scores


class KeepAllScorer:
    """Scores everything 1.0: no filtering, order decides (the safe default)."""

    def score(self, question: str, parts: Sequence[str]) -> list[float]:
        return [1.0] * len(parts)
