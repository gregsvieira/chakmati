"""BM25 over a handful of passages: pure Python, no model, no network. Shared by the research (which passages answer?) and the files (which pieces of
an attached file answer the question?). Accents and plurals are ignored, Portuguese and English stop words are dropped."""

import math
import re
import unicodedata
from collections import Counter
from collections.abc import Sequence

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
