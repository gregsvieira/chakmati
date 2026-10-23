from datetime import datetime, timedelta, timezone

import pytest

from liteagent.agenda.ics import IcsCalendarProvider
from liteagent.agenda.models import NewEvent

UTC = timezone.utc
BRT = timezone(timedelta(hours=-3))
D = lambda day, hour=0, minute=0, tz=UTC: datetime(2026, 10, day, hour, minute, tzinfo=tz)  # noqa: E731
WEEK = (D(1), D(31))


@pytest.fixture
def provider(tmp_path):
    return IcsCalendarProvider(str(tmp_path / "agenda.ics"))


def test_missing_file_is_an_empty_calendar(provider):
    assert provider.list_events(*WEEK) == []


def test_create_then_list_preserves_the_instant_and_text(provider, tmp_path):
    created = provider.create_event(
        NewEvent("Reunião; planejamento, Q4", D(24, 15, 0, BRT), D(24, 16, 30, BRT), location="Sala 2", notes="linha 1\nlinha 2")
    )
    assert created.id and created.title == "Reunião; planejamento, Q4"
    (listed,) = provider.list_events(*WEEK)
    assert listed.id == created.id
    assert listed.start == D(24, 15, 0, BRT) and listed.end == D(24, 16, 30, BRT)  # same instant
    assert (listed.location, listed.notes) == ("Sala 2", "linha 1\nlinha 2")
    assert not list(tmp_path.glob("*.tmp"))  # atomic write left nothing behind


def test_all_day_events_round_trip(provider):
    provider.create_event(NewEvent("Feriado", D(12), D(13), all_day=True))
    (e,) = provider.list_events(*WEEK)
    assert e.all_day and e.start.date().isoformat() == "2026-10-12" and e.end.date().isoformat() == "2026-10-13"


def test_range_filter_overlap_and_sort_order(provider):
    provider.create_event(NewEvent("B", D(20, 10), D(20, 11)))
    provider.create_event(NewEvent("A", D(18, 10), D(18, 11)))
    provider.create_event(NewEvent("Cruza a meia-noite", D(19, 23), D(20, 1)))
    provider.create_event(NewEvent("Fora", D(28, 10), D(28, 11)))
    titles = [e.title for e in provider.list_events(D(19), D(21))]
    assert titles == ["Cruza a meia-noite", "B"]
    assert [e.title for e in provider.list_events(*WEEK)] == ["A", "Cruza a meia-noite", "B", "Fora"]


def test_delete_removes_only_that_event_and_unknown_id_raises(provider):
    a = provider.create_event(NewEvent("A", D(18, 10), D(18, 11)))
    b = provider.create_event(NewEvent("B", D(19, 10), D(19, 11)))
    provider.delete_event(a.id)
    assert [e.id for e in provider.list_events(*WEEK)] == [b.id]
    with pytest.raises(KeyError):
        provider.delete_event("nope")


RECURRING = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//other app//EN
BEGIN:VEVENT
UID:weekly-1
DTSTAMP:20260101T000000Z
DTSTART:20261005T090000Z
DTEND:20261005T093000Z
RRULE:FREQ=WEEKLY;COUNT=3
SUMMARY:Standup
END:VEVENT
BEGIN:VEVENT
UID:floating-1
DTSTAMP:20260101T000000Z
DTSTART:20261014T140000
DTEND:20261014T150000
SUMMARY:Sem fuso
END:VEVENT
END:VCALENDAR
"""


def test_reads_recurring_events_and_floating_times_written_by_other_apps(tmp_path):
    path = tmp_path / "other.ics"
    path.write_text(RECURRING)
    p = IcsCalendarProvider(str(path))
    events = p.list_events(*WEEK)
    standups = [e for e in events if e.title == "Standup"]
    assert [e.start.day for e in standups] == [5, 12, 19]
    floating = next(e for e in events if e.title == "Sem fuso")
    assert floating.start.tzinfo is not None and floating.start.replace(tzinfo=None) == datetime(2026, 10, 14, 14, 0)


def test_creating_in_an_existing_file_keeps_the_other_events(tmp_path):
    path = tmp_path / "other.ics"
    path.write_text(RECURRING)
    p = IcsCalendarProvider(str(path))
    p.create_event(NewEvent("Novo", D(25, 10), D(25, 11)))
    titles = {e.title for e in p.list_events(*WEEK)}
    assert {"Standup", "Sem fuso", "Novo"} <= titles
    assert "PRODID:-//other app//EN" in path.read_text()


def test_a_corrupt_file_is_reported_and_never_overwritten(tmp_path):
    path = tmp_path / "bad.ics"
    path.write_text("this is not an ics file")
    p = IcsCalendarProvider(str(path))
    with pytest.raises(ValueError, match="not a valid"):
        p.list_events(*WEEK)
    with pytest.raises(ValueError, match="not a valid"):
        p.create_event(NewEvent("x", D(25, 10), D(25, 11)))
    assert path.read_text() == "this is not an ics file"
