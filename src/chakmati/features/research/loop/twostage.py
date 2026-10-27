"""Two-stage part scoring: a cheap Laya relevance pre-filter, then an LLM verifier
only on the parts that survived.

All scorers here are synchronous: ThinkLoop runs `score` in a worker thread.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import httpx

from chakmati.shared.gate.laya_gate import Predictor
from chakmati.features.research.loop.scorer import PartScorer

log = logging.getLogger(__name__)

RELEVANCE_QUESTION: dict[str, Any] = {
    "relevance": {
        "type": "score",
        "instructions": (
            "How correct and useful is this candidate step for answering the question?"
        ),
        "criteria": ["wrong or useless", "partly useful", "correct and useful"],
    }
}
_LEVELS = len(RELEVANCE_QUESTION["relevance"]["criteria"])


def _default_relevance_predictor() -> Predictor:
    from laya import Router  # optional dependency; ImportError handled by caller

    router = Router(max_loaded=3)

    def predict(text: str, questions: dict[str, Any]) -> Any:
        # English checkpoint: best at separating relevant from irrelevant (see spec).
        return router.predict({"body": text}, questions, model="english")

    return predict


class LayaRelevanceScorer:
    """Laya `score` question on the English checkpoint, normalised to 0..1.

    Fail-safe: if Laya is missing or errors, every part scores 1.0 (nothing is filtered).
    """

    def __init__(self, predictor: Predictor | None = None):
        self._predictor = predictor
        self._unavailable = False

    def _resolve(self) -> Predictor | None:
        if self._predictor is None and not self._unavailable:
            try:
                # looked up on the module so tests can monkeypatch it
                self._predictor = _default_relevance_predictor()
            except ImportError:
                log.warning("laya is not installed; relevance pre-filter is disabled")
                self._unavailable = True
        return self._predictor

    def score(self, question: str, parts: Sequence[str]) -> list[float]:
        predictor = self._resolve()
        if predictor is None:
            return [1.0] * len(parts)
        out: list[float] = []
        for part in parts:
            text = f"Question: {question}\nCandidate step: {part}"
            try:
                level = float(predictor(text, RELEVANCE_QUESTION)["answers"]["relevance"]["score"])
                out.append(level / (_LEVELS - 1))
            except Exception:
                log.warning("laya relevance failed for a part; keeping it", exc_info=True)
                out.append(1.0)
        return out


class LLMVerifier:
    """Asks the LLM whether each part is correct AND useful: yes -> 1.0, anything else -> 0.0."""

    SYSTEM = (
        "Decide if the candidate step is factually correct AND useful for answering the "
        "question. Reply with exactly one word: yes or no."
    )

    def __init__(
        self,
        base_url: str,
        model: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 300.0,
    ):
        self._model = model
        self._http = httpx.Client(base_url=base_url, transport=transport, timeout=timeout)
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def _ask(self, question: str, part: str) -> float:
        response = self._http.post(
            "/api/chat",
            json={
                "model": self._model,
                "stream": False,
                "think": False,
                "options": {"temperature": 0, "num_predict": 8},
                "messages": [
                    {"role": "system", "content": self.SYSTEM},
                    {"role": "user", "content": f"Question: {question}\nCandidate step: {part}"},
                ],
            },
        )
        response.raise_for_status()
        data = response.json()
        self.calls += 1
        self.prompt_tokens += data.get("prompt_eval_count", 0)
        self.completion_tokens += data.get("eval_count", 0)
        return 1.0 if data["message"]["content"].strip().lower().startswith(("yes", "sim")) else 0.0

    def score(self, question: str, parts: Sequence[str]) -> list[float]:
        out: list[float] = []
        for part in parts:
            try:
                out.append(self._ask(question, part))
            except Exception:
                log.warning("llm verification failed for a part; dropping it", exc_info=True)
                out.append(0.0)
        return out


@dataclass
class StageStats:
    total: int = 0
    prefiltered_out: int = 0
    verified: int = 0


class TwoStageScorer:
    """Cheap relevance pre-filter, then the (expensive) verifier on survivors only."""

    def __init__(self, prefilter: PartScorer, verifier: PartScorer, cutoff: float = 0.2):
        self._pre = prefilter
        self._ver = verifier
        self._cutoff = cutoff
        self.stats = StageStats()

    def score(self, question: str, parts: Sequence[str]) -> list[float]:
        pre = self._pre.score(question, parts)
        survivors = [i for i, s in enumerate(pre) if s >= self._cutoff]
        verdicts = self._ver.score(question, [parts[i] for i in survivors]) if survivors else []
        out = [0.0] * len(parts)
        for i, v in zip(survivors, verdicts, strict=True):
            out[i] = v
        self.stats.total += len(parts)
        self.stats.prefiltered_out += len(parts) - len(survivors)
        self.stats.verified += len(survivors)
        return out
