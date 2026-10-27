from chakmati.loop.compare import summarize
from chakmati.loop.evalset import ALL_ITEMS


def test_summarize_perfect_scorer():
    scores = {"perfect": [0.95 if i.label else 0.05 for i in ALL_ITEMS]}
    s = summarize(scores, ALL_ITEMS, thresholds=(0.5, 0.89))["perfect"]
    assert s["good_vs_irrelevant"] == 1.0 and s["good_vs_wrong"] == 1.0
    assert s["mean"] == {"good": 0.95, "irrelevant": 0.05, "wrong": 0.05}
    n_good = sum(1 for i in ALL_ITEMS if i.kind == "good")
    n_irr = sum(1 for i in ALL_ITEMS if i.kind == "irrelevant")
    assert s["passing"][0.89] == {"good": n_good, "irrelevant": 0, "wrong": 0}
    assert s["totals"] == {"good": n_good, "irrelevant": n_irr, "wrong": n_irr}


def test_summarize_threshold_blocks_low_scores():
    scores = {"low": [0.2] * len(ALL_ITEMS)}
    s = summarize(scores, ALL_ITEMS, thresholds=(0.5,))["low"]
    assert s["passing"][0.5] == {"good": 0, "irrelevant": 0, "wrong": 0}
    assert s["good_vs_irrelevant"] == 0.5
