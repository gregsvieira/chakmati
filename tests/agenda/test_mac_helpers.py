from datetime import datetime, timedelta, timezone

import pytest

from chakmati.agenda.mac import (
    allday_end_from_eventkit,
    allday_end_to_eventkit,
    make_event_id,
    split_event_id,
)

UTC = timezone.utc


def test_event_id_round_trip_distinguishes_occurrences_of_a_recurring_event():
    a = make_event_id("ABC:123", 1_700_000_000.0)
    b = make_event_id("ABC:123", 1_700_086_400.0)
    assert a != b
    assert split_event_id(a) == ("ABC:123", 1_700_000_000)
    assert split_event_id(b) == ("ABC:123", 1_700_086_400)


def test_event_id_split_handles_identifiers_containing_the_separator():
    ident = "x|y|z"
    assert split_event_id(make_event_id(ident, 5.0)) == (ident, 5)


def test_event_id_split_rejects_garbage():
    with pytest.raises(ValueError):
        split_event_id("no-separator")


def test_allday_end_conversion_between_exclusive_and_eventkit_inclusive():
    start = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)
    exclusive_end = start + timedelta(days=1)  # our model: the day after the last day, at 00:00
    inclusive = allday_end_to_eventkit(exclusive_end)
    assert inclusive == exclusive_end - timedelta(seconds=1)  # EventKit: 23:59:59 on the last day
    assert allday_end_from_eventkit(inclusive) == exclusive_end
    assert allday_end_from_eventkit(exclusive_end) == exclusive_end  # already midnight: unchanged
