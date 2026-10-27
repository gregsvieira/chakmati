from datetime import datetime, timedelta, timezone

import pytest

from chakmati.features.agenda.models import MAX_TITLE, CalendarEvent, NewEvent

UTC = timezone.utc
T0 = datetime(2026, 10, 24, 15, 0, tzinfo=UTC)


def test_new_event_accepts_a_valid_event():
    e = NewEvent("Reunião", T0, T0 + timedelta(hours=1), location="Sala 2")
    assert e.title == "Reunião" and e.calendar is None and not e.all_day


def test_title_is_stripped_and_required():
    assert NewEvent("  Dentista  ", T0, T0 + timedelta(hours=1)).title == "Dentista"
    with pytest.raises(ValueError, match="title"):
        NewEvent("   ", T0, T0 + timedelta(hours=1))
    with pytest.raises(ValueError, match="title"):
        NewEvent("x" * (MAX_TITLE + 1), T0, T0 + timedelta(hours=1))


def test_naive_datetimes_are_rejected():
    with pytest.raises(ValueError, match="timezone"):
        NewEvent("x", datetime(2026, 10, 24, 15, 0), datetime(2026, 10, 24, 16, 0))


def test_end_must_be_after_start_and_duration_is_bounded():
    with pytest.raises(ValueError, match="end"):
        NewEvent("x", T0, T0)
    with pytest.raises(ValueError, match="end"):
        NewEvent("x", T0, T0 - timedelta(minutes=1))
    with pytest.raises(ValueError, match="long"):
        NewEvent("x", T0, T0 + timedelta(days=400))


def test_all_day_event_may_end_the_same_day_start():
    day = datetime(2026, 10, 24, 0, 0, tzinfo=UTC)
    assert NewEvent("Feriado", day, day + timedelta(days=1), all_day=True).all_day


def test_calendar_event_summary_is_human_readable():
    e = CalendarEvent("id1", "Reunião", T0, T0 + timedelta(hours=1), calendar="Trabalho", location="Sala 2")
    s = e.summary()
    assert "Reunião" in s and "15:00" in s and "16:00" in s and "Sala 2" in s and "Trabalho" in s
    allday = CalendarEvent("id2", "Feriado", T0.replace(hour=0), T0.replace(hour=0) + timedelta(days=1), all_day=True)
    assert "dia inteiro" in allday.summary()


def test_summary_shows_the_weekday_so_a_wrong_date_is_easy_to_spot():
    # 2026-10-24 is a Saturday
    assert "sáb 2026-10-24" in CalendarEvent("i", "x", T0, T0 + timedelta(hours=1)).summary()
    allday = CalendarEvent("j", "y", T0.replace(hour=0), T0.replace(hour=0) + timedelta(days=1), all_day=True)
    assert "sáb 2026-10-24" in allday.summary()
    multi = CalendarEvent("k", "z", T0, T0 + timedelta(days=2)).summary()
    assert "sáb 2026-10-24" in multi and "seg 2026-10-26" in multi
