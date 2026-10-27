from chakmati.research.passages_experiment import gold_in_top, rank_of_first


def test_rank_of_first_is_one_based_and_breaks_ties_by_input_order():
    scores = [0.1, 0.9, 0.9, 0.3]
    assert rank_of_first(scores, [False, False, True, False]) == 2  # idx1 and idx2 tie, idx1 first
    assert rank_of_first(scores, [True, False, False, False]) == 4
    assert rank_of_first(scores, [False] * 4) is None


def test_gold_in_top_counts_gold_among_top_k():
    scores = [0.1, 0.9, 0.8, 0.3, 0.7]
    gold = [True, False, True, False, True]
    assert gold_in_top(scores, gold, 3) == 2  # top3 = idx1, idx2, idx4 -> gold at idx2, idx4
    assert gold_in_top(scores, gold, 1) == 0
