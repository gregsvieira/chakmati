"""Calendar service with a human-in-the-loop write path.

The model (or any caller) can only PROPOSE a change; a proposal is stored as a pending action and nothing
is written to the calendar until `approve` is called, which the HTTP layer exposes only to the user's UI.
"""

import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from .models import CalendarEvent, CalendarProvider, NewEvent

PENDING, EXECUTING, EXECUTED, REJECTED, FAILED, EXPIRED = (
    "pending", "executing", "executed", "rejected", "failed", "expired",
)


class ActionNotPending(Exception):
    """The action was already approved, rejected, executed or has failed."""


class ActionExpired(Exception):
    """The proposal sat unanswered for too long and can no longer be approved."""


@dataclass(frozen=True)
class Action:
    id: str
    kind: str  # "calendar.create" | "calendar.delete"
    summary: str
    status: str
    payload: dict
    result: str | None = None
    error: str | None = None
    expires_at: float = 0.0


class ActionStore:
    def __init__(self, path: str):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS actions (
                 id TEXT PRIMARY KEY, kind TEXT NOT NULL, summary TEXT NOT NULL, status TEXT NOT NULL,
                 payload TEXT NOT NULL, result TEXT, error TEXT, created_at REAL NOT NULL, expires_at REAL NOT NULL
               )"""
        )
        self._db.commit()

    @staticmethod
    def _action(row: sqlite3.Row) -> Action:
        return Action(row["id"], row["kind"], row["summary"], row["status"], json.loads(row["payload"]),
                      row["result"], row["error"], row["expires_at"])

    def add(self, kind: str, summary: str, payload: dict, created: float, expires: float) -> Action:
        action_id = uuid.uuid4().hex
        with self._lock:
            self._db.execute(
                "INSERT INTO actions (id, kind, summary, status, payload, created_at, expires_at) VALUES (?,?,?,?,?,?,?)",
                (action_id, kind, summary, PENDING, json.dumps(payload, ensure_ascii=False), created, expires),
            )
            self._db.commit()
        return self.get(action_id)  # type: ignore[return-value]

    def get(self, action_id: str) -> Action | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM actions WHERE id = ?", (action_id,)).fetchone()
        return self._action(row) if row else None

    def transition(self, action_id: str, from_status: str, to_status: str) -> bool:
        """Atomically move an action between states; False if it was not in `from_status`."""
        with self._lock:
            cur = self._db.execute(
                "UPDATE actions SET status = ? WHERE id = ? AND status = ?", (to_status, action_id, from_status)
            )
            self._db.commit()
            return cur.rowcount == 1

    def finish(self, action_id: str, status: str, result: str | None, error: str | None) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE actions SET status = ?, result = ?, error = ? WHERE id = ?", (status, result, error, action_id)
            )
            self._db.commit()

    def pending(self, now: float) -> list[Action]:
        with self._lock:
            self._db.execute(
                "UPDATE actions SET status = ? WHERE status = ? AND expires_at < ?", (EXPIRED, PENDING, now)
            )
            self._db.commit()
            rows = self._db.execute(
                "SELECT * FROM actions WHERE status = ? ORDER BY created_at", (PENDING,)
            ).fetchall()
        return [self._action(r) for r in rows]


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


class CalendarService:
    def __init__(
        self,
        provider: CalendarProvider,
        actions: ActionStore,
        ttl_seconds: float = 3600.0,
        now: Callable[[], float] = time.time,
    ):
        self._provider = provider
        self._actions = actions
        self._ttl = ttl_seconds
        self._now = now

    # ---- reading (no approval needed)
    def events(self, start: datetime, end: datetime) -> list[CalendarEvent]:
        return self._provider.list_events(start, end)

    # ---- proposing (stores a pending action; touches nothing)
    def propose_create(self, new: NewEvent) -> Action:
        now = self._now()
        return self._actions.add("calendar.create", f"Criar evento: {new.summary()}", _new_event_payload(new),
                                 now, now + self._ttl)

    def propose_delete(self, event: CalendarEvent) -> Action:
        now = self._now()
        return self._actions.add("calendar.delete", f"Apagar evento: {event.summary()}",
                                 {"event_id": event.id, "title": event.title}, now, now + self._ttl)

    def pending(self) -> list[Action]:
        return self._actions.pending(self._now())

    # ---- deciding (called only by the user's UI)
    def approve(self, action_id: str) -> Action:
        action = self._actions.get(action_id)
        if action is None:
            raise KeyError(action_id)
        if action.status == PENDING and self._now() > action.expires_at:
            self._actions.transition(action_id, PENDING, EXPIRED)
            raise ActionExpired(action_id)
        if not self._actions.transition(action_id, PENDING, EXECUTING):  # claims it: no double execution
            raise ActionNotPending(f"{action_id} is {action.status}")
        try:
            if action.kind == "calendar.create":
                created = self._provider.create_event(_new_event_from(action.payload))
                result = f"Evento criado (id {created.id}): {created.summary()}"
            elif action.kind == "calendar.delete":
                self._provider.delete_event(action.payload["event_id"])
                result = f"Evento apagado: {action.payload['title']}"
            else:
                raise ValueError(f"unknown action kind {action.kind}")
        except Exception as exc:
            self._actions.finish(action_id, FAILED, None, f"{type(exc).__name__}: {exc}")
        else:
            self._actions.finish(action_id, EXECUTED, result, None)
        return self._actions.get(action_id)  # type: ignore[return-value]

    def reject(self, action_id: str) -> Action:
        action = self._actions.get(action_id)
        if action is None:
            raise KeyError(action_id)
        if not self._actions.transition(action_id, PENDING, REJECTED):
            raise ActionNotPending(f"{action_id} is {action.status}")
        return self._actions.get(action_id)  # type: ignore[return-value]
