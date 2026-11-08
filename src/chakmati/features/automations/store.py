from __future__ import annotations

"""Automations on disk (the same SQLite file as jobs and actions), plus a small log of what each one did."""

import json
import sqlite3
import threading
import uuid
from dataclasses import dataclass

from chakmati.features.automations.models import Spec, parse_spec


@dataclass(frozen=True)
class Automation:
    id: str
    spec: Spec
    enabled: bool
    created_at: float
    runs: int
    last_run_at: float | None

    @property
    def name(self) -> str:
        return self.spec.name


class AutomationStore:
    def __init__(self, path: str):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._db.executescript(
            """CREATE TABLE IF NOT EXISTS automations (
                 id TEXT PRIMARY KEY, name TEXT NOT NULL, spec TEXT NOT NULL, enabled INTEGER NOT NULL,
                 created_at REAL NOT NULL, runs INTEGER NOT NULL DEFAULT 0, last_run_at REAL
               );
               CREATE TABLE IF NOT EXISTS automation_runs (
                 id INTEGER PRIMARY KEY AUTOINCREMENT, automation_id TEXT NOT NULL, key TEXT NOT NULL,
                 outcome TEXT NOT NULL, at REAL NOT NULL
               );
               CREATE INDEX IF NOT EXISTS automation_runs_by_key ON automation_runs (automation_id, key, at);"""
        )
        self._db.commit()

    @staticmethod
    def _automation(row: sqlite3.Row) -> Automation:
        data = json.loads(row["spec"])
        return Automation(row["id"], parse_spec(data), bool(row["enabled"]), row["created_at"], row["runs"], row["last_run_at"])

    def create(self, spec: Spec, now: float) -> Automation:
        auto_id = uuid.uuid4().hex
        body = {"name": spec.name, "trigger": spec.trigger, "action": spec.action}
        with self._lock:
            self._db.execute(
                "INSERT INTO automations (id, name, spec, enabled, created_at) VALUES (?,?,?,?,?)",
                (auto_id, spec.name, json.dumps(body, ensure_ascii=False), 1, now),
            )
            self._db.commit()
        return self.get(auto_id)  # type: ignore[return-value]

    def get(self, auto_id: str) -> Automation | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM automations WHERE id = ?", (auto_id,)).fetchone()
        return self._automation(row) if row else None

    def list(self, enabled_only: bool = False) -> list[Automation]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM automations WHERE enabled = 1 ORDER BY created_at" if enabled_only else "SELECT * FROM automations ORDER BY created_at").fetchall()
        return [self._automation(r) for r in rows]

    def set_enabled(self, auto_id: str, enabled: bool) -> bool:
        with self._lock:
            cur = self._db.execute("UPDATE automations SET enabled = ? WHERE id = ?", (1 if enabled else 0, auto_id))
            self._db.commit()
            return cur.rowcount == 1

    def delete(self, auto_id: str) -> bool:
        with self._lock:
            self._db.execute("DELETE FROM automation_runs WHERE automation_id = ?", (auto_id,))
            cur = self._db.execute("DELETE FROM automations WHERE id = ?", (auto_id,))
            self._db.commit()
            return cur.rowcount == 1

    def record_run(self, auto_id: str, key: str, outcome: str, now: float) -> None:
        with self._lock:
            self._db.execute("INSERT INTO automation_runs (automation_id, key, outcome, at) VALUES (?,?,?,?)", (auto_id, key, outcome, now))
            if outcome == "ok" or outcome.startswith("parcial"):  # a failed attempt is logged but neither counts as a run nor starts a cooldown
                self._db.execute("UPDATE automations SET runs = runs + 1, last_run_at = ? WHERE id = ?", (now, auto_id))
            self._db.commit()

    def last_run(self, auto_id: str, key: str) -> float | None:
        with self._lock:
            row = self._db.execute("SELECT MAX(at) AS at FROM automation_runs WHERE automation_id = ? AND key = ? AND (outcome = 'ok' OR outcome LIKE 'parcial%')", (auto_id, key)).fetchone()
        return row["at"] if row and row["at"] is not None else None

    def recent_runs(self, auto_id: str, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT key, outcome, at FROM automation_runs WHERE automation_id = ? ORDER BY id DESC LIMIT ?", (auto_id, limit)).fetchall()
        return [dict(r) for r in rows]
