import asyncio
import sqlite3
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

QUEUED, RUNNING, DONE, FAILED = "queued", "running", "done", "failed"


@dataclass(frozen=True)
class Job:
    id: str
    route: str
    prompt: str
    status: str
    result: str | None
    error: str | None


class JobStore:
    def __init__(self, path: str):
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute(
            """CREATE TABLE IF NOT EXISTS jobs (
                 id TEXT PRIMARY KEY,
                 route TEXT NOT NULL,
                 prompt TEXT NOT NULL,
                 status TEXT NOT NULL,
                 result TEXT,
                 error TEXT,
                 created_at REAL NOT NULL,
                 updated_at REAL NOT NULL
               )"""
        )
        self._db.commit()

    @staticmethod
    def _job(row: sqlite3.Row) -> Job:
        return Job(
            row["id"], row["route"], row["prompt"],
            row["status"], row["result"], row["error"],
        )

    def create(self, route: str, prompt: str) -> str:
        job_id = uuid.uuid4().hex
        now = time.time()
        self._db.execute(
            "INSERT INTO jobs VALUES (?, ?, ?, ?, NULL, NULL, ?, ?)",
            (job_id, route, prompt, QUEUED, now, now),
        )
        self._db.commit()
        return job_id

    def get(self, job_id: str) -> Job | None:
        row = self._db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return self._job(row) if row else None

    def claim_next(self) -> Job | None:
        row = self._db.execute(
            "SELECT id FROM jobs WHERE status = ? ORDER BY rowid LIMIT 1", (QUEUED,)
        ).fetchone()
        if row is None:
            return None
        self._db.execute(
            "UPDATE jobs SET status = ?, updated_at = ? WHERE id = ?",
            (RUNNING, time.time(), row["id"]),
        )
        self._db.commit()
        return self.get(row["id"])

    def _set(self, job_id: str, status: str, result: str | None, error: str | None) -> None:
        self._db.execute(
            "UPDATE jobs SET status = ?, result = ?, error = ?, updated_at = ? WHERE id = ?",
            (status, result, error, time.time(), job_id),
        )
        self._db.commit()

    def finish(self, job_id: str, result: str) -> None:
        self._set(job_id, DONE, result, None)

    def fail(self, job_id: str, error: str) -> None:
        self._set(job_id, FAILED, None, error)

    def requeue_running(self) -> int:
        cur = self._db.execute(
            "UPDATE jobs SET status = ?, updated_at = ? WHERE status = ?",
            (QUEUED, time.time(), RUNNING),
        )
        self._db.commit()
        return cur.rowcount


Handler = Callable[[Job], Awaitable[str]]


class Worker:
    def __init__(self, store: JobStore, handler: Handler, poll_seconds: float = 0.5):
        self._store = store
        self._handler = handler
        self._poll = poll_seconds

    async def run_once(self) -> bool:
        job = self._store.claim_next()
        if job is None:
            return False
        try:
            result = await self._handler(job)
        except Exception as exc:
            self._store.fail(job.id, f"{type(exc).__name__}: {exc}")
        else:
            self._store.finish(job.id, result)
        return True

    async def run_forever(self) -> None:
        while True:
            if not await self.run_once():
                await asyncio.sleep(self._poll)
