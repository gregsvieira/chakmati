"""Portable calendar backend: one iCalendar (.ics) file. Works the same on macOS, Windows and Linux,
and the file can be shared with other apps (Thunderbird, khal, ...)."""

import os
import tempfile
import threading
import uuid
from datetime import date, datetime, timedelta, timezone

import icalendar
import recurring_ical_events

from .models import CalendarEvent, NewEvent

PRODID = "-//lite-agent//agenda//PT"


def _as_aware(value: date | datetime) -> tuple[datetime, bool]:
    """Return (aware datetime, is_all_day). All-day dates become local midnight; floating times are local."""
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.astimezone()), False
    midnight = datetime(value.year, value.month, value.day).astimezone()
    return midnight, True


class IcsCalendarProvider:
    name = "ics"

    def __init__(self, path: str, calendar_name: str = "Agenda"):
        self._path = path
        self._calendar_name = calendar_name
        self._lock = threading.Lock()

    def _load(self) -> icalendar.Calendar:
        if not os.path.exists(self._path):
            cal = icalendar.Calendar()
            cal.add("prodid", PRODID)
            cal.add("version", "2.0")
            return cal
        try:
            with open(self._path, "rb") as f:
                return icalendar.Calendar.from_ical(f.read())
        except Exception as exc:
            raise ValueError(f"{self._path} is not a valid iCalendar file: {exc}") from exc

    def _save(self, cal: icalendar.Calendar) -> None:
        directory = os.path.dirname(os.path.abspath(self._path))
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(cal.to_ical())
            os.replace(tmp, self._path)  # atomic: readers never see a half-written file
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    @staticmethod
    def _event(component) -> CalendarEvent:
        start, all_day = _as_aware(component.get("DTSTART").dt)
        raw_end = component.get("DTEND")
        if raw_end is not None:
            end, _ = _as_aware(raw_end.dt)
        elif component.get("DURATION") is not None:
            end = start + component.get("DURATION").dt
        else:
            end = start + (timedelta(days=1) if all_day else timedelta(0))
        return CalendarEvent(
            id=str(component.get("UID", "")),
            title=str(component.get("SUMMARY", "")),
            start=start,
            end=end,
            all_day=all_day,
            location=str(component.get("LOCATION", "")),
            notes=str(component.get("DESCRIPTION", "")),
        )

    def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        with self._lock:
            cal = self._load()
        occurrences = recurring_ical_events.of(cal).between(start, end)
        events = [self._event(c) for c in occurrences]
        return sorted(events, key=lambda e: (e.start, e.title))

    def create_event(self, new: NewEvent) -> CalendarEvent:
        with self._lock:
            cal = self._load()
            event = icalendar.Event()
            uid = f"{uuid.uuid4()}@lite-agent"
            event.add("uid", uid)
            event.add("dtstamp", datetime.now(timezone.utc))
            event.add("summary", new.title)
            if new.all_day:
                event.add("dtstart", new.start.date())
                event.add("dtend", new.end.date())
            else:
                event.add("dtstart", new.start)
                event.add("dtend", new.end)
            if new.location:
                event.add("location", new.location)
            if new.notes:
                event.add("description", new.notes)
            cal.add_component(event)
            self._save(cal)
        return CalendarEvent(uid, new.title, new.start, new.end, new.all_day, new.location, new.notes,
                             new.calendar or self._calendar_name)

    def delete_event(self, event_id: str) -> None:
        with self._lock:
            cal = self._load()
            keep = [c for c in cal.subcomponents if not (c.name == "VEVENT" and str(c.get("UID", "")) == event_id)]
            if len(keep) == len(cal.subcomponents):
                raise KeyError(event_id)
            cal.subcomponents = keep
            self._save(cal)
