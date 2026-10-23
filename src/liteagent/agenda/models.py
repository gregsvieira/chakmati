from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

MAX_TITLE = 200
MAX_DURATION = timedelta(days=366)


@dataclass(frozen=True)
class CalendarEvent:
    id: str
    title: str
    start: datetime
    end: datetime
    all_day: bool = False
    location: str = ""
    notes: str = ""
    calendar: str = ""

    def summary(self) -> str:
        """One human-readable line, used in answers and in approval prompts."""
        if self.all_day:
            when = f"{self.start:%Y-%m-%d} (dia inteiro)"
        elif self.start.date() == self.end.date():
            when = f"{self.start:%Y-%m-%d %H:%M}–{self.end:%H:%M}"
        else:
            when = f"{self.start:%Y-%m-%d %H:%M} → {self.end:%Y-%m-%d %H:%M}"
        parts = [f"{self.title} — {when}"]
        if self.location:
            parts.append(f"local: {self.location}")
        if self.calendar:
            parts.append(f"agenda: {self.calendar}")
        return " | ".join(parts)


@dataclass(frozen=True)
class NewEvent:
    title: str
    start: datetime
    end: datetime
    all_day: bool = False
    location: str = ""
    notes: str = ""
    calendar: str | None = None

    def __post_init__(self) -> None:
        title = self.title.strip()
        if not title or len(title) > MAX_TITLE:
            raise ValueError(f"title must be 1-{MAX_TITLE} characters")
        object.__setattr__(self, "title", title)
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("start and end must include a timezone")
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if self.end - self.start > MAX_DURATION:
            raise ValueError("event is too long (more than 366 days)")

    def summary(self) -> str:
        return CalendarEvent("", self.title, self.start, self.end, self.all_day, self.location, self.notes,
                             self.calendar or "").summary()


class CalendarProvider(Protocol):
    """A calendar backend. Synchronous: callers run it in a worker thread."""

    name: str

    def list_events(self, start: datetime, end: datetime) -> list[CalendarEvent]: ...

    def create_event(self, new: NewEvent) -> CalendarEvent: ...

    def delete_event(self, event_id: str) -> None: ...
