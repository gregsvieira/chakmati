import logging
from collections.abc import Callable, Mapping
from typing import Any

from chakmati.shared.gate.base import Gate, GateResult, Route

log = logging.getLogger(__name__)

ROUTE_QUESTION: dict[str, Any] = {
    "route": {
        "type": "choice",
        "instructions": "What does the user want the assistant to do?",
        "criteria": {
            "chat": "greetings, small talk, simple questions answerable from general knowledge",
            "research": "look something up on the web, find current information, compare sources",
            "task": "write or run code, create or edit files, multi-step work",
        },
    }
}

Predictor = Callable[[str, dict[str, Any]], Mapping[str, Any]]


def _default_predictor() -> Predictor:
    from laya import Router  # optional dependency; ImportError handled by caller

    router = Router()  # downloads the checkpoint on first use

    def predict(text: str, questions: dict[str, Any]) -> Mapping[str, Any]:
        # The HTTP API uses {"body": text} as state; mirror it here.
        return router.predict({"body": text}, questions)

    return predict


class LayaGate:
    def __init__(
        self,
        fallback: Gate,
        min_confidence: float = 0.6,
        predictor: Predictor | None = None,
    ):
        self._fallback = fallback
        self._min = min_confidence
        self._predictor = predictor
        self._unavailable = False

    def _resolve_predictor(self) -> Predictor | None:
        if self._predictor is None and not self._unavailable:
            try:
                self._predictor = _default_predictor()
            except ImportError:
                log.warning("laya is not installed; using the fallback gate")
                self._unavailable = True
        return self._predictor

    def classify(self, text: str) -> GateResult:
        predictor = self._resolve_predictor()
        if predictor is None:
            return self._fallback.classify(text)
        try:
            answer = predictor(text, ROUTE_QUESTION)["answers"]["route"]
            route = Route(answer["choice"])
            confidence = float(answer["confidence"])
        except Exception:
            log.warning("laya prediction failed; using the fallback gate", exc_info=True)
            return self._fallback.classify(text)
        if confidence < self._min:
            return self._fallback.classify(text)
        return GateResult(route, confidence, "laya")
