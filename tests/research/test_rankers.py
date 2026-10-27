import json

import httpx

from chakmati.research.rankers import Bm25Scorer, EmbeddingScorer


def test_bm25_ranks_passages_that_share_rare_query_terms_higher():
    parts = [
        "Como verificar a versão do Python instalada no seu computador.",
        "Python 3.13.17 - Oct. 21, 2026 é a versão estável mais recente.",
        "Receita de bolo de cenoura com cobertura de chocolate.",
    ]
    scores = Bm25Scorer().score("versão estável atual do Python", parts)
    assert scores[1] > scores[0] > scores[2]
    assert max(scores) == 1.0 and min(scores) >= 0.0


def test_bm25_ignores_accents_case_stopwords_and_simple_plurals():
    parts = ["VERSÕES estáveis disponíveis", "banana prata"]
    s = Bm25Scorer().score("versao estavel", parts)
    assert s[0] > s[1] == 0.0


def test_bm25_empty_and_no_overlap():
    assert Bm25Scorer().score("q", []) == []
    assert Bm25Scorer().score("zzz", ["aaa", "bbb"]) == [0.0, 0.0]


def vec_for(text: str) -> list[float]:
    text = text.lower()
    return [1.0 if "python" in text else 0.0, 1.0 if "bolo" in text else 0.0, 0.1]


def test_embedding_scorer_uses_prefixes_and_cosine():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.setdefault("inputs", []).extend(body["input"])
        seen["model"] = body["model"]
        return httpx.Response(200, json={"embeddings": [vec_for(t) for t in body["input"]]})

    scorer = EmbeddingScorer("http://o.test", "nomic-embed-text", transport=httpx.MockTransport(handler))
    scores = scorer.score("versão do Python", ["Python 3.13 lançado", "receita de bolo"])
    assert scores[0] > scores[1] >= 0.0
    assert seen["model"] == "nomic-embed-text"
    assert seen["inputs"][0] == "search_query: versão do Python"
    assert seen["inputs"][1] == "search_document: Python 3.13 lançado"


def test_embedding_scorer_fail_safe_and_empty():
    bad = EmbeddingScorer("http://o.test", "m", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    assert bad.score("q", ["a", "b"]) == [1.0, 1.0]
    assert bad.score("q", []) == []
