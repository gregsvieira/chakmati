"""macOS calendar backend: EventKit through PyObjC. Reads and writes every calendar configured in
Calendar.app (iCloud, Google, Exchange, local). The first use asks the user for permission.

Only the pure helpers are unit-tested; the EventKit calls need a Mac and the user's permission, and are
checked with `python -m chakmati.agenda.mac_check`.
"""

import threading
from datetime import datetime, timedelta

from .models import CalendarEvent, NewEvent

# EKAuthorizationStatus
NOT_DETERMINED, RESTRICTED, DENIED, FULL_ACCESS, WRITE_ONLY = 0, 1, 2, 3, 4
SPAN_THIS_EVENT = 0
_SEP = "|"


def make_event_id(identifier: str, start_timestamp: float) -> str:
    """EventKit gives every occurrence of a recurring event the same identifier; add the start time."""
    return f"{identifier}{_SEP}{int(start_timestamp)}"


def split_event_id(event_id: str) -> tuple[str, int]:
    identifier, sep, stamp = event_id.rpartition(_SEP)
    if not sep or not identifier:
        raise ValueError(f"not a macOS event id: {event_id!r}")
    return identifier, int(stamp)


def allday_end_to_eventkit(exclusive_end: datetime) -> datetime:
    """Our all-day events end at the 00:00 after the last day; EventKit ends them at 23:59:59 on the last day."""
    return exclusive_end - timedelta(seconds=1)


def allday_end_from_eventkit(end: datetime) -> datetime:
    if end.hour == 23 and end.minute == 59:
        return (end + timedelta(minutes=1)).replace(second=0, microsecond=0)
    return end


class MacEventKitProvider:
    name = "macos"

    def __init__(self, default_calendar: str | None = None, access_timeout: float = 120.0):
        from EventKit import EKEntityTypeEvent, EKEventStore

        self._entity = EKEntityTypeEvent
        self._default_calendar = default_calendar
        self._store = EKEventStore.alloc().init()
        self._ensure_access(access_timeout)

    # ---- permission
    def _ensure_access(self, timeout: float) -> None:
        from EventKit import EKEventStore

        status = EKEventStore.authorizationStatusForEntityType_(self._entity)
        if status == FULL_ACCESS:
            return
        if status in (RESTRICTED, DENIED):
            raise PermissionError(
                "Calendar access is blocked. Allow it in System Settings > Privacy & Security > Calendars."
            )
        answered = threading.Event()
        outcome: dict = {}

        def handler(granted, error):  # called by EventKit on its own queue
            outcome["granted"], outcome["error"] = bool(granted), error
            answered.set()

        if hasattr(self._store, "requestFullAccessToEventsWithCompletion_"):  # macOS 14+
            self._store.requestFullAccessToEventsWithCompletion_(handler)
        else:
            self._store.requestAccessToEntityType_completion_(self._entity, handler)
        if not answered.wait(timeout):
            raise PermissionError(f"no answer to the Calendar permission dialog within {int(timeout)} s")
        if not outcome["granted"]:
            raise PermissionError("Calendar access was not granted")

    # ---- conversions
    @staticmethod
    def _ns(dt: datetime):
        from Foundation import NSDate

        return NSDate.dateWithTimeIntervalSince1970_(dt.timestamp())

    @staticmethod
    def _py(ns_date) -> datetime:
        return datetime.fromtimestamp(ns_date.timeIntervalSince1970()).astimezone()

    def _to_model(self, ev) -> CalendarEvent:
        start, end = self._py(ev.startDate()), self._py(ev.endDate())
        all_day = bool(ev.isAllDay())
        if all_day:
            end = allday_end_from_eventkit(end)
        cal = ev.calendar()
        return CalendarEvent(
            id=make_event_id(str(ev.eventIdentifier()), ev.startDate().timeIntervalSince1970()),
            title=str(ev.title() or ""),
            start=start,
            end=end,
            all_day=all_day,
            location=str(ev.location() or ""),
            notes=str(ev.notes() or ""),
            calendar=str(cal.title()) if cal is not None else "",
        )

    # ---- API
    def list_calendars(self) -> list[str]:
        return [str(c.title()) for c in self._store.calendarsForEntityType_(self._entity)
                if c.allowsContentModifications()]

    def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        predicate = self._store.predicateForEventsWithStartDate_endDate_calendars_(self._ns(start), self._ns(end), None)
        events = [self._to_model(e) for e in (self._store.eventsMatchingPredicate_(predicate) or [])]
        return sorted(events, key=lambda e: (e.start, e.title))

    def _writable_calendar(self, name: str | None):
        wanted = name or self._default_calendar
        if wanted:
            for cal in self._store.calendarsForEntityType_(self._entity):
                if str(cal.title()) == wanted and cal.allowsContentModifications():
                    return cal
            raise ValueError(f"no writable calendar named {wanted!r}")
        cal = self._store.defaultCalendarForNewEvents()
        if cal is None:
            raise ValueError("Calendar.app has no default calendar for new events")
        return cal

    def create_event(self, new: NewEvent) -> CalendarEvent:
        from EventKit import EKEvent

        ev = EKEvent.eventWithEventStore_(self._store)
        ev.setTitle_(new.title)
        ev.setStartDate_(self._ns(new.start))
        ev.setAllDay_(new.all_day)
        ev.setEndDate_(self._ns(allday_end_to_eventkit(new.end) if new.all_day else new.end))
        if new.location:
            ev.setLocation_(new.location)
        if new.notes:
            ev.setNotes_(new.notes)
        ev.setCalendar_(self._writable_calendar(new.calendar))
        ok, error = self._store.saveEvent_span_commit_error_(ev, SPAN_THIS_EVENT, True, None)
        if not ok:
            raise RuntimeError(f"EventKit could not save the event: {error}")
        return self._to_model(ev)

    def delete_event(self, event_id: str) -> None:
        identifier, stamp = split_event_id(event_id)
        window = datetime.fromtimestamp(stamp).astimezone()
        predicate = self._store.predicateForEventsWithStartDate_endDate_calendars_(
            self._ns(window - timedelta(seconds=1)), self._ns(window + timedelta(seconds=2)), None
        )
        for ev in self._store.eventsMatchingPredicate_(predicate) or []:
            if str(ev.eventIdentifier()) == identifier and int(ev.startDate().timeIntervalSince1970()) == stamp:
                ok, error = self._store.removeEvent_span_commit_error_(ev, SPAN_THIS_EVENT, True, None)
                if not ok:
                    raise RuntimeError(f"EventKit could not delete the event: {error}")
                return
        raise KeyError(event_id)
