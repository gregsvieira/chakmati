import asyncio
import sqlite3
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
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
    partial: str = ""


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
                 updated_at REAL NOT NULL,
                 partial TEXT NOT NULL DEFAULT ''
               )"""
        )
        columns = {row["name"] for row in self._db.execute("PRAGMA table_info(jobs)")}
        if "partial" not in columns:  # database created before streaming existed
            self._db.execute("ALTER TABLE jobs ADD COLUMN partial TEXT NOT NULL DEFAULT ''")
        self._db.commit()

    @staticmethod
    def _job(row: sqlite3.Row) -> Job:
        return Job(
            row["id"], row["route"], row["prompt"],
            row["status"], row["result"], row["error"], row["partial"],
        )

    def create(self, route: str, prompt: str) -> str:
        job_id = uuid.uuid4().hex
        now = time.time()
        self._db.execute(
            "INSERT INTO jobs (id, route, prompt, status, result, error, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, NULL, NULL, ?, ?)",
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

    def set_partial(self, job_id: str, text: str) -> None:
        self._db.execute(
            "UPDATE jobs SET partial = ?, updated_at = ? WHERE id = ?", (text, time.time(), job_id)
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
StreamHandler = Callable[[Job], AsyncIterator[str]]


class Worker:
    def __init__(
        self,
        store: JobStore,
        handler: Handler | None,
        poll_seconds: float = 0.5,
        stream_handler: StreamHandler | None = None,
        flush_interval: float = 0.1,
    ):
        self._store = store
        self._handler = handler
        self._poll = poll_seconds
        self._stream_handler = stream_handler
        self._flush = flush_interval
        self._wakeup = asyncio.Event()

    def wake(self) -> None:
        """Tell an idle worker that a job was just queued, so it does not wait for the next poll."""
        self._wakeup.set()

    async def _run_stream(self, job: Job) -> str:
        """Consume the stream, saving the text so far (`partial`) at most every `flush_interval`."""
        assert self._stream_handler is not None
        parts: list[str] = []
        last = 0.0
        loop = asyncio.get_running_loop()
        try:
            async for delta in self._stream_handler(job):
                parts.append(delta)
                now = loop.time()
                if now - last >= self._flush:
                    self._store.set_partial(job.id, "".join(parts))
                    last = now
        finally:
            self._store.set_partial(job.id, "".join(parts))
        return "".join(parts)

    async def run_once(self) -> bool:
        job = self._store.claim_next()
        if job is None:
            return False
        try:
            if self._stream_handler is not None:
                result = await self._run_stream(job)
            else:
                assert self._handler is not None
                result = await self._handler(job)
        except Exception as exc:
            self._store.fail(job.id, f"{type(exc).__name__}: {exc}")
        else:
            self._store.finish(job.id, result)
        return True

    async def run_forever(self) -> None:
        while True:
            if not await self.run_once():
                try:
                    await asyncio.wait_for(self._wakeup.wait(), timeout=self._poll)
                except asyncio.TimeoutError:
                    pass
                self._wakeup.clear()
