"""Human-in-the-loop approvals shared by every integration (calendar, WhatsApp, ...).

A caller (the model included) can only PROPOSE an action. A proposal is stored as a pending action and nothing
happens until `approve` is called, which the HTTP layer exposes only to the user's UI. One action inbox for all.
"""

import json
import sqlite3
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass


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




class ApprovalService:
    """Base for services whose writes go through approval. Subclasses set `prefix` ("calendar.", "whatsapp.")
    and implement `_execute`, which does the real work for one approved action and returns a result text."""

    prefix = ""

    def __init__(self, actions: ActionStore, ttl_seconds: float = 3600.0, now: Callable[[], float] = time.time):
        self._actions = actions
        self._ttl = ttl_seconds
        self._now = now

    def _propose(self, kind: str, summary: str, payload: dict) -> Action:
        now = self._now()
        return self._actions.add(kind, summary, payload, now, now + self._ttl)

    def _mine(self, action_id: str) -> Action:
        action = self._actions.get(action_id)
        if action is None or not action.kind.startswith(self.prefix):
            raise KeyError(action_id)
        return action

    def owns(self, action_id: str) -> bool:
        action = self._actions.get(action_id)
        return action is not None and action.kind.startswith(self.prefix)

    def pending(self) -> list[Action]:
        return [a for a in self._actions.pending(self._now()) if a.kind.startswith(self.prefix)]

    def _execute(self, action: Action) -> str:
        raise NotImplementedError

    def approve(self, action_id: str) -> Action:
        action = self._mine(action_id)
        if action.status == PENDING and self._now() > action.expires_at:
            self._actions.transition(action_id, PENDING, EXPIRED)
            raise ActionExpired(action_id)
        if not self._actions.transition(action_id, PENDING, EXECUTING):  # claims it: no double execution
            raise ActionNotPending(f"{action_id} is {action.status}")
        try:
            result = self._execute(action)
        except Exception as exc:
            self._actions.finish(action_id, FAILED, None, f"{type(exc).__name__}: {exc}")
        else:
            self._actions.finish(action_id, EXECUTED, result, None)
        return self._actions.get(action_id)  # type: ignore[return-value]

    def reject(self, action_id: str) -> Action:
        action = self._mine(action_id)
        if not self._actions.transition(action_id, PENDING, REJECTED):
            raise ActionNotPending(f"{action_id} is {action.status}")
        return self._actions.get(action_id)  # type: ignore[return-value]
