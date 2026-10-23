"""Calendar service with a human-in-the-loop write path (see liteagent.approvals)."""

import time
from collections.abc import Callable
from datetime import datetime

from ..approvals import (  # noqa: F401  (re-exported: other modules and tests import these from here)
    EXECUTED,
    EXECUTING,
    EXPIRED,
    FAILED,
    PENDING,
    REJECTED,
    Action,
    ActionExpired,
    ActionNotPending,
    ActionStore,
    ApprovalService,
)
from .models import CalendarEvent, CalendarProvider, NewEvent

def _new_event_payload(new: NewEvent) -> dict:
    return {
        "title": new.title, "start": new.start.isoformat(), "end": new.end.isoformat(),
        "all_day": new.all_day, "location": new.location, "notes": new.notes, "calendar": new.calendar,
    }


def _new_event_from(payload: dict) -> NewEvent:
    return NewEvent(
        payload["title"], datetime.fromisoformat(payload["start"]), datetime.fromisoformat(payload["end"]),
        payload["all_day"], payload["location"], payload["notes"], payload["calendar"],
    )


class CalendarService(ApprovalService):
    prefix = "calendar."

    def __init__(
        self,
        provider: CalendarProvider,
        actions: ActionStore,
        ttl_seconds: float = 3600.0,
        now: Callable[[], float] = time.time,
    ):
        super().__init__(actions, ttl_seconds, now)
        self._provider = provider

    # ---- reading (no approval needed)
    def events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        return self._provider.list_events(start, end)

    # ---- proposing (stores a pending action; touches nothing)
    def propose_create(self, new: NewEvent) -> Action:
        return self._propose("calendar.create", f"Criar evento: {new.summary()}", _new_event_payload(new))

    def propose_delete(self, event: CalendarEvent) -> Action:
        return self._propose("calendar.delete", f"Apagar evento: {event.summary()}",
                             {"event_id": event.id, "title": event.title})

    # ---- executing (called by ApprovalService.approve, only after the user approved)
    def _execute(self, action: Action) -> str:
        if action.kind == "calendar.create":
            created = self._provider.create_event(_new_event_from(action.payload))
            return f"Evento criado (id {created.id}): {created.summary()}"
        if action.kind == "calendar.delete":
            self._provider.delete_event(action.payload["event_id"])
            return f"Evento apagado: {action.payload['title']}"
        raise ValueError(f"unknown action kind {action.kind}")
