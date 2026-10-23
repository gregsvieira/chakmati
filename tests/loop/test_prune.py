import pytest

from liteagent.loop.prune import PruneConfig, prune


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
