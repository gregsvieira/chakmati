"""Passage rankers that score "does this passage match the question?" without Laya.

Both implement PartScorer (score(question, parts) -> list[float]) and are synchronous.
"""

import logging
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence

import httpx

log = logging.getLogger(__name__)

_STOPWORDS = frozenset(
    "a o as os um uma uns umas de do da dos das em no na nos nas por para com sem sobre e ou que "
    "se ao aos pela pelo pelas pelos como qual quais the an of to in on for and or is are was were "
    "be by with from at as it its this that these those what which pesquise pesquisar busque buscar "
    "procure me meu minha seu sua".split()
)
_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)*")


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def _stem(token: str) -> str:
    if len(token) > 4 and token.endswith("oes"):
        return token[:-3] + "ao"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokenize(text: str) -> list[str]:
    tokens = _TOKEN.findall(_strip_accents(text).lower())
    return [_stem(t) for t in tokens if t not in _STOPWORDS and len(t) > 1]


class Bm25Scorer:
    """Okapi BM25 over the candidate passages themselves (the corpus is `parts`).

    Scores are scaled so the best passage is 1.0. Pure Python, no model, no network.
    """

    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self._k1 = k1
        self._b = b

    def score(self, question: str, parts: Sequence[str]) -> list[float]:
        if not parts:
            return []
        docs = [Counter(tokenize(p)) for p in parts]
        lengths = [sum(d.values()) for d in docs]
        avg = (sum(lengths) / len(lengths)) or 1.0
        n = len(docs)
        df = Counter(t for d in docs for t in d)
        query = set(tokenize(question))
        raw: list[float] = []
        for d, length in zip(docs, lengths, strict=True):
            total = 0.0
            for t in query:
                tf = d.get(t, 0)
                if not tf:
                    continue
                idf = math.log((n - df[t] + 0.5) / (df[t] + 0.5) + 1)
                total += idf * tf * (self._k1 + 1) / (tf + self._k1 * (1 - self._b + self._b * length / avg))
            raw.append(total)
        top = max(raw)
        return [s / top for s in raw] if top > 0 else [0.0] * len(raw)


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
