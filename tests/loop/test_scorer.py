from liteagent.gate import laya_gate
from liteagent.loop.scorer import PART_QUESTION, LayaPartScorer


def noul_result(p):
    return {"answers": {"useful": {"noul": p}}}


def test_scores_each_part_in_order_with_question_and_part_in_state():
    seen = []

    def predictor(text, questions):
        assert questions is PART_QUESTION
        seen.append(text)
        return noul_result(0.9 if "bom" in text else 0.1)

    scorer = LayaPartScorer(predictor)
    scores = scorer.score("Q?", ["parte bom", "parte ruim"])
    assert scores == [0.9, 0.1]
    assert seen == [
        "Question: Q?\nCandidate step: parte bom",
        "Question: Q?\nCandidate step: parte ruim",
    ]


def test_part_that_errors_scores_one_and_others_still_scored():
    def predictor(text, questions):
        if "boom" in text:
            raise RuntimeError("x")
        return noul_result(0.2)

    scores = LayaPartScorer(predictor).score("Q", ["ok", "boom", "ok2"])
    assert scores == [0.2, 1.0, 0.2]


def test_malformed_result_scores_one():
    scorer = LayaPartScorer(lambda text, questions: {})
    assert scorer.score("Q", ["a"]) == [1.0]


def test_laya_missing_scores_everything_one(monkeypatch):
    def missing():
        raise ImportError("no laya")

    monkeypatch.setattr(laya_gate, "_default_predictor", missing)
    scorer = LayaPartScorer()
    assert scorer.score("Q", ["a", "b"]) == [1.0, 1.0]
    assert scorer.score("Q", ["a"]) == [1.0]  # remembered, no retry crash


def test_empty_parts():
    assert LayaPartScorer(lambda t, q: noul_result(0.5)).score("Q", []) == []


from liteagent.loop.scorer import KeepAllScorer


def test_keep_all_scorer_scores_everything_one():
    assert KeepAllScorer().score("Q", ["a", "b", "c"]) == [1.0, 1.0, 1.0]
    assert KeepAllScorer().score("Q", []) == []
