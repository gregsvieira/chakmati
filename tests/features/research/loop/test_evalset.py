from chakmati.features.research.loop.evalset import ITEMS, pairwise_accuracy


def test_dataset_shape():
    assert len(ITEMS) == 12
    assert {i.kind for i in ITEMS} == {"good", "irrelevant", "wrong"}
    assert all((i.label == 1) == (i.kind == "good") for i in ITEMS)
    assert len({i.question for i in ITEMS}) == 3


def test_perfect_scores():
    scores = [1.0 if i.label else 0.0 for i in ITEMS]
    assert pairwise_accuracy(ITEMS, scores) == {"irrelevant": 1.0, "wrong": 1.0}


def test_all_ties_count_half():
    assert pairwise_accuracy(ITEMS, [0.5] * len(ITEMS)) == {
        "irrelevant": 0.5,
        "wrong": 0.5,
    }


def test_wrong_ranked_above_good_scores_zero_for_wrong_only():
    scores = [
        0.2 if i.kind == "good" else 0.9 if i.kind == "wrong" else 0.0 for i in ITEMS
    ]
    result = pairwise_accuracy(ITEMS, scores)
    assert result["wrong"] == 0.0
    assert result["irrelevant"] == 1.0


from chakmati.features.research.loop.evalset import strategy_report
from chakmati.features.research.loop.prune import prune_by_rank


def test_strategy_report_perfect_scores_top_half():
    scores = [1.0 if i.label else 0.0 for i in ITEMS]
    report = strategy_report(ITEMS, scores, {"top50": lambda p, s: prune_by_rank(p, s, 0.5)})
    assert report["top50"] == {
        "good_kept": 1.0,
        "irrelevant_dropped": 1.0,
        "wrong_dropped": 1.0,
    }


def test_strategy_report_keep_everything():
    report = strategy_report(ITEMS, [0.5] * len(ITEMS), {"all": lambda p, s: list(p)})
    assert report["all"] == {
        "good_kept": 1.0,
        "irrelevant_dropped": 0.0,
        "wrong_dropped": 0.0,
    }


from chakmati.features.research.loop.evalset import ALL_ITEMS, ITEMS_EXTRA


def test_extra_items_shape_and_combined_set():
    assert len(ITEMS_EXTRA) == 20
    assert len({i.question for i in ITEMS_EXTRA}) == 5
    assert {i.kind for i in ITEMS_EXTRA} == {"good", "irrelevant", "wrong"}
    assert ALL_ITEMS == ITEMS + ITEMS_EXTRA
    assert len({i.question for i in ALL_ITEMS}) == 8
