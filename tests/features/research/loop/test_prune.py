import pytest

from chakmati.features.research.loop.prune import PruneConfig, prune


def test_drops_below_threshold():
    assert prune(["a", "b", "c"], [0.9, 0.2, 0.7], PruneConfig(0.5)) == ["a", "c"]


def test_keeps_original_order():
    assert prune(["a", "b", "c"], [0.6, 0.9, 0.7], PruneConfig(0.5)) == ["a", "b", "c"]


def test_max_keep_takes_best_by_score_but_returns_original_order():
    cfg = PruneConfig(threshold=0.0, max_keep=2)
    assert prune(["a", "b", "c", "d"], [0.1, 0.9, 0.5, 0.8], cfg) == ["b", "d"]


def test_min_keep_floor_when_all_below_threshold():
    cfg = PruneConfig(threshold=0.9, min_keep=1)
    assert prune(["a", "b"], [0.1, 0.4], cfg) == ["b"]


def test_empty_input():
    assert prune([], [], PruneConfig()) == []


def test_length_mismatch_raises():
    with pytest.raises(ValueError):
        prune(["a"], [0.1, 0.2], PruneConfig())


from chakmati.features.research.loop.prune import prune_by_rank, prune_relative_to_best


def test_by_rank_keeps_top_fraction_in_original_order():
    parts, scores = ["a", "b", "c", "d"], [0.1, 0.9, 0.5, 0.8]
    assert prune_by_rank(parts, scores, keep_fraction=0.5) == ["b", "d"]


def test_by_rank_ignores_absolute_scale():
    # every score is tiny, yet the best are still kept (a fixed threshold would drop all)
    assert prune_by_rank(["a", "b", "c", "d"], [0.01, 0.12, 0.02, 0.11], 0.5) == ["b", "d"]


def test_by_rank_min_and_max_keep():
    parts, scores = ["a", "b", "c", "d"], [0.1, 0.9, 0.5, 0.8]
    assert prune_by_rank(parts, scores, keep_fraction=0.1, min_keep=2) == ["b", "d"]
    assert prune_by_rank(parts, scores, keep_fraction=1.0, max_keep=3) == ["b", "c", "d"]


def test_by_rank_empty_and_mismatch():
    assert prune_by_rank([], [], 0.5) == []
    with pytest.raises(ValueError):
        prune_by_rank(["a"], [0.1, 0.2], 0.5)


def test_relative_to_best_keeps_scores_near_the_top():
    parts, scores = ["a", "b", "c"], [0.10, 0.12, 0.02]
    assert prune_relative_to_best(parts, scores, ratio=0.5) == ["a", "b"]


def test_relative_to_best_always_keeps_the_best_and_handles_empty():
    assert prune_relative_to_best(["a", "b"], [0.0, 0.0], ratio=0.9) == ["a", "b"]
    assert prune_relative_to_best([], [], ratio=0.5) == []
