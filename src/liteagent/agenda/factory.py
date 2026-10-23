"""Builds the calendar service from the settings."""

import sys
import threading
from datetime import datetime

from ..config import Settings
from .ics import IcsCalendarProvider
from .models import CalendarEvent, CalendarProvider, NewEvent
from .service import ActionStore, CalendarService


def _make_mac(default_calendar: str):
    from .mac import MacEventKitProvider

    return MacEventKitProvider(default_calendar or None)


class LazyProvider:
    """Builds the real provider on first use, so the app starts even while the macOS permission dialog is
    still unanswered; a failed build (e.g. permission denied) is retried on the next call."""

    def __init__(self, make, name: str):
        self._make = make
        self.name = name
        self._real: CalendarProvider | None = None
        self._lock = threading.Lock()

    def _get(self) -> CalendarProvider:
        with self._lock:
            if self._real is None:
                self._real = self._make()
            return self._real

    def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        return self._get().list_events(start, end)

    def create_event(self, new: NewEvent) -> CalendarEvent:
        return self._get().create_event(new)

    def delete_event(self, event_id: str) -> None:
        self._get().delete_event(event_id)


def build_calendar(settings: Settings) -> CalendarService | None:
    backend = settings.calendar_backend
    if backend == "off":
        return None
    if backend not in {"auto", "macos", "ics"}:
        raise ValueError(f"unknown calendar_backend {backend!r} (use off, auto, macos or ics)")
    if backend == "macos" or (backend == "auto" and sys.platform == "darwin"):
        provider: CalendarProvider = LazyProvider(lambda: _make_mac(settings.calendar_name), "macos")
    else:
        # Windows (Outlook COM) and Linux (Evolution Data Server / CalDAV) backends are not implemented
        # yet; the portable .ics file works everywhere.
        provider = IcsCalendarProvider(settings.calendar_ics_path, settings.calendar_name or "Agenda")
    return CalendarService(provider, ActionStore(settings.db_path))
