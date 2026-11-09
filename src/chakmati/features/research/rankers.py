"""Passage rankers that score "does this passage match the question?" without Laya.

Both implement PartScorer (score(question, parts) -> list[float]) and are synchronous.
"""

import logging
import math
from collections.abc import Sequence

import httpx

log = logging.getLogger(__name__)

from chakmati.shared.bm25 import Bm25Scorer, tokenize  # noqa: F401  (they live in shared now; re-exported for the experiments)


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class EmbeddingScorer:
    """Cosine similarity between the question and each passage using an Ollama embedding model.

    nomic-embed-text expects task prefixes; they are added here. Fail-safe: if the embedding
    call fails every passage scores 1.0, i.e. the original order is kept.
    """

    def __init__(
        self,
        base_url: str,
        model: str = "nomic-embed-text",
        transport: httpx.BaseTransport | None = None,
        batch: int = 32,
        timeout: float = 120.0,
    ):
        self._model = model
        self._batch = batch
        self._http = httpx.Client(base_url=base_url, transport=transport, timeout=timeout)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), self._batch):
            response = self._http.post(
                "/api/embed", json={"model": self._model, "input": texts[i : i + self._batch]}
            )
            response.raise_for_status()
            out.extend(response.json()["embeddings"])
        return out

    def score(self, question: str, parts: Sequence[str]) -> list[float]:
        if not parts:
            return []
        try:
            vectors = self._embed(
                [f"search_query: {question}"] + [f"search_document: {p}" for p in parts]
            )
        except Exception:
            log.warning("embedding failed; keeping the original order", exc_info=True)
            return [1.0] * len(parts)
        query, docs = vectors[0], vectors[1:]
        return [max(_cosine(query, d), 0.0) for d in docs]
