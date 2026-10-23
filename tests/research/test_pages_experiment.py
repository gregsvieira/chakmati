from liteagent.research.pages_experiment import fetch_wait, usable_pages


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
