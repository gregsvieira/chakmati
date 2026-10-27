from chakmati.features.research.evalset import LabelledResult, ranking_metrics, with_injected_negatives


def item(q, rank, relevant, source="natural"):
    return LabelledResult(q, rank, f"t{q}{rank}", f"https://x/{q}/{rank}", "s", relevant, source)


BASE = [
    item("a", 1, 1), item("a", 2, 1), item("a", 3, 0),
    item("b", 1, 1), item("b", 2, 0), item("b", 3, 1),
]


def test_injected_negatives_come_from_other_queries_and_are_irrelevant():
    out = with_injected_negatives(BASE, per_query=2)
    injected = [i for i in out if i.source == "injected"]
    assert len(injected) == 4
    assert all(i.relevant == 0 for i in injected)
    for i in injected:
        assert i.query in {"a", "b"}
        assert not any(b.url == i.url and b.query == i.query for b in BASE)
    assert [i for i in out if i.source == "natural"] == BASE


def test_ranking_metrics_perfect_and_rank_baseline():
    perfect = [float(i.relevant) for i in BASE]
    m = ranking_metrics(BASE, perfect)
    # each query has only 3 items, one irrelevant: the top 3 always contains it -> 2/3
    assert m["pairwise"] == 1.0 and abs(m["precision_at_3"] - 2 / 3) < 1e-9
    by_rank = [-float(i.rank) for i in BASE]
    m2 = ranking_metrics(BASE, by_rank)
    # query a: relevant at 1,2 beat irrelevant at 3 -> 1.0; query b: (1 vs 2)=1, (3 vs 2)=0 -> 0.5
    assert m2["pairwise"] == (2 + 1) / (2 + 2)


def test_ranking_metrics_all_ties():
    assert ranking_metrics(BASE, [0.5] * len(BASE))["pairwise"] == 0.5
