from chakmati.research.pages_experiment import fetch_wait, usable_pages


def test_fetch_wait_is_the_slowest_of_the_first_n_capped_by_the_deadline():
    durations = [0.2, 0.9, 6.0, 0.3]
    assert fetch_wait(durations, 1, 2.0) == 0.2
    assert fetch_wait(durations, 2, 2.0) == 0.9
    assert fetch_wait(durations, 3, 2.0) == 2.0  # the 6 s page is cut at the deadline
    assert fetch_wait(durations, 4, 2.0) == 2.0
    assert fetch_wait([], 2, 2.0) == 0.0


def test_usable_pages_requires_success_within_the_deadline():
    bodies = ["a", None, "c", "d"]
    durations = [0.2, 0.1, 3.0, 1.0]
    assert usable_pages(bodies, durations, 4, 2.0) == ["a", None, None, "d"]
    assert usable_pages(bodies, durations, 2, 2.0) == ["a", None]


from chakmati.research.pages_experiment import first_k_successes


def test_first_k_successes_picks_the_k_fastest_usable_pages_in_rank_order():
    bodies = [None, "b", "c", "d"]
    durations = [0.1, 0.5, 0.2, 0.9]
    indices, wait = first_k_successes(bodies, durations, 2, 2.0)
    assert indices == [1, 2]            # page 0 failed; 2 (0.2s) and 1 (0.5s) are the first two to succeed
    assert wait == 0.5                  # the moment the 2nd success arrived


def test_first_k_successes_ignores_pages_after_the_deadline_and_uses_what_arrived():
    bodies = ["a", "b", "c", "d"]
    durations = [3.0, 0.4, 5.0, 2.5]
    indices, wait = first_k_successes(bodies, durations, 2, 2.0)
    assert indices == [1] and wait == 2.0  # only one page made it; waited until the deadline


def test_first_k_successes_nothing_usable():
    assert first_k_successes([None, None], [0.1, 0.2], 2, 2.0) == ([], 0.2)
