import json

import httpx

from chakmati.features.research.loop import twostage
from chakmati.features.research.loop.twostage import (
    RELEVANCE_QUESTION,
    LayaRelevanceScorer,
    LLMVerifier,
    TwoStageScorer,
)


class FixedScorer:
    def __init__(self, scores):
        self.scores, self.calls = scores, []

    def score(self, question, parts):
        self.calls.append((question, list(parts)))
        return list(self.scores[: len(parts)]) if len(self.scores) >= len(parts) else self.scores


def test_prefilter_drops_low_relevance_and_verifier_sees_only_survivors():
    pre = FixedScorer([0.9, 0.01, 0.8])
    ver = FixedScorer([1.0, 0.0])  # verdicts for the 2 survivors
    scorer = TwoStageScorer(pre, ver, cutoff=0.2)
    assert scorer.score("Q", ["a", "b", "c"]) == [1.0, 0.0, 0.0]
    assert ver.calls == [("Q", ["a", "c"])]
    assert (scorer.stats.total, scorer.stats.prefiltered_out, scorer.stats.verified) == (3, 1, 2)


def test_verifier_not_called_when_everything_is_prefiltered():
    pre, ver = FixedScorer([0.0, 0.0]), FixedScorer([])
    assert TwoStageScorer(pre, ver, cutoff=0.2).score("Q", ["a", "b"]) == [0.0, 0.0]
    assert ver.calls == []


def test_stats_accumulate_across_calls():
    scorer = TwoStageScorer(FixedScorer([0.9]), FixedScorer([1.0]), cutoff=0.2)
    scorer.score("Q", ["a"])
    scorer.score("Q", ["a"])
    assert (scorer.stats.total, scorer.stats.verified) == (2, 2)


def llm_handler(replies, seen):
    it = iter(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {"content": next(it)},
                "prompt_eval_count": 10,
                "eval_count": 2,
            },
        )

    return handler


def test_llm_verifier_parses_yes_no_and_counts_usage():
    seen = []
    v = LLMVerifier(
        "http://o.test", "m", transport=httpx.MockTransport(llm_handler(["Yes", "no", "Sim.", "???"], seen))
    )
    assert v.score("Q?", ["a", "b", "c", "d"]) == [1.0, 0.0, 1.0, 0.0]
    assert (v.calls, v.prompt_tokens, v.completion_tokens) == (4, 40, 8)
    body = seen[0]
    assert body["think"] is False and body["stream"] is False
    assert body["options"]["temperature"] == 0
    assert "Question: Q?\nCandidate step: a" == body["messages"][1]["content"]
    assert "yes or no" in body["messages"][0]["content"]


def test_llm_verifier_error_scores_zero():
    v = LLMVerifier(
        "http://o.test", "m", transport=httpx.MockTransport(lambda r: httpx.Response(500))
    )
    assert v.score("Q", ["a"]) == [0.0]


def relevance_result(level):
    return {"answers": {"relevance": {"score": level}}}


def test_laya_relevance_scorer_normalizes_level_to_0_1():
    seen = []

    def predictor(text, questions):
        assert questions is RELEVANCE_QUESTION
        seen.append(text)
        return relevance_result(1.0 if "bom" in text else 0.02)

    s = LayaRelevanceScorer(predictor).score("Q?", ["parte bom", "ruído"])
    assert s == [0.5, 0.01]
    assert seen[0] == "Question: Q?\nCandidate step: parte bom"


def test_laya_relevance_scorer_fail_safe(monkeypatch):
    def boom(text, questions):
        raise RuntimeError("x")

    assert LayaRelevanceScorer(boom).score("Q", ["a"]) == [1.0]
    assert LayaRelevanceScorer(lambda t, q: {}).score("Q", ["a"]) == [1.0]

    def missing():
        raise ImportError("no laya")

    monkeypatch.setattr(twostage, "_default_relevance_predictor", missing)
    assert LayaRelevanceScorer().score("Q", ["a", "b"]) == [1.0, 1.0]
