import asyncio
import pytest

from liteagent.jobs import DONE, FAILED, QUEUED, RUNNING, JobStore, Worker


@pytest.fixture
def store():
    return JobStore(":memory:")


def test_create_and_get(store):
    job_id = store.create("research", "find x")
    job = store.get(job_id)
    assert job.status == QUEUED
    assert job.route == "research"
    assert job.prompt == "find x"
    assert job.result is None and job.error is None


def test_get_unknown_returns_none(store):
    assert store.get("nope") is None


def test_claim_next_is_fifo_and_marks_running(store):
    first = store.create("task", "one")
    second = store.create("task", "two")
    claimed = store.claim_next()
    assert claimed.id == first
    assert claimed.status == RUNNING
    assert store.claim_next().id == second
    assert store.claim_next() is None


def test_finish_and_fail(store):
    a, b = store.create("task", "a"), store.create("task", "b")
    store.finish(a, "ok")
    store.fail(b, "bad")
    assert store.get(a).status == DONE and store.get(a).result == "ok"
    assert store.get(b).status == FAILED and store.get(b).error == "bad"


def test_requeue_running(store):
    job_id = store.create("task", "a")
    store.claim_next()
    assert store.requeue_running() == 1
    assert store.get(job_id).status == QUEUED


async def test_worker_run_once_success(store):
    job_id = store.create("research", "q")

    async def handler(job):
        return f"answer to {job.prompt}"

    worker = Worker(store, handler)
    assert await worker.run_once() is True
    assert store.get(job_id).status == DONE
    assert store.get(job_id).result == "answer to q"


async def test_worker_run_once_failure_is_recorded(store):
    job_id = store.create("research", "q")

    async def handler(job):
        raise ValueError("kaput")

    assert await Worker(store, handler).run_once() is True
    job = store.get(job_id)
    assert job.status == FAILED
    assert job.error == "ValueError: kaput"


async def test_worker_run_once_empty_queue(store):
    async def handler(job):
        raise AssertionError("must not run")

    assert await Worker(store, handler).run_once() is False


import sqlite3

from liteagent.jobs import Worker as _Worker  # noqa: E402  (same class, explicit for the streaming tests)


def test_partial_defaults_empty_and_can_be_updated(store):
    job_id = store.create("research", "q")
    assert store.get(job_id).partial == ""
    store.set_partial(job_id, "Olá")
    assert store.get(job_id).partial == "Olá"


def test_existing_database_without_partial_column_is_migrated(tmp_path):
    path = str(tmp_path / "old.db")
    db = sqlite3.connect(path)
    db.execute(
        """CREATE TABLE jobs (id TEXT PRIMARY KEY, route TEXT NOT NULL, prompt TEXT NOT NULL,
           status TEXT NOT NULL, result TEXT, error TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL)"""
    )
    db.execute("INSERT INTO jobs VALUES ('a','task','p','queued',NULL,NULL,1,1)")
    db.commit()
    db.close()
    migrated = JobStore(path)
    assert migrated.get("a").partial == ""
    migrated.set_partial("a", "x")
    assert migrated.get("a").partial == "x"


async def test_worker_stream_handler_accumulates_partial_and_finishes(store):
    job_id = store.create("research", "q")
    snapshots = []

    async def stream(job):
        for piece in ["Ol", "á", "!"]:
            yield piece
            snapshots.append(store.get(job.id).partial)

    worker = _Worker(store, handler=None, stream_handler=stream, flush_interval=0)
    assert await worker.run_once() is True
    job = store.get(job_id)
    assert job.status == DONE and job.result == "Olá!"
    assert snapshots == ["Ol", "Olá", "Olá!"][: len(snapshots)] and snapshots[0] == "Ol"


async def test_worker_stream_failure_midway_is_recorded(store):
    job_id = store.create("research", "q")

    async def stream(job):
        yield "par"
        raise ValueError("cut")

    await _Worker(store, handler=None, stream_handler=stream, flush_interval=0).run_once()
    job = store.get(job_id)
    assert job.status == FAILED and job.error == "ValueError: cut"
    assert job.partial == "par"


async def test_wake_makes_the_worker_pick_up_a_job_without_waiting_for_the_poll(store):
    done = asyncio.Event()

    async def handler(job):
        done.set()
        return "ok"

    worker = Worker(store, handler, poll_seconds=30)  # would sleep 30 s between polls
    task = asyncio.create_task(worker.run_forever())
    await asyncio.sleep(0.05)  # the worker is now idle, sleeping
    store.create("research", "q")
    worker.wake()
    await asyncio.wait_for(done.wait(), timeout=2)
    task.cancel()


# ------------------------------------------------------------------------------------------------ stopping a job
async def test_a_running_job_can_be_stopped_and_the_next_one_still_runs():
    import asyncio
    from liteagent.jobs import CANCELLED
    store = JobStore(":memory:")
    started, ran = asyncio.Event(), []

    async def handler(job):
        if job.prompt == "slow":
            started.set()
            try:
                await asyncio.sleep(30)
            finally:
                ran.append("cleaned up")   # what the browser agent does: close the browser
        return job.prompt

    worker = Worker(store, handler)
    slow, quick = store.create("task", "slow"), store.create("task", "quick")
    first = asyncio.create_task(worker.run_once())
    await started.wait()
    assert worker.cancel(slow) is True
    await first
    assert store.get(slow).status == "failed" and store.get(slow).error == CANCELLED and ran == ["cleaned up"]
    await worker.run_once()
    assert store.get(quick).status == "done" and store.get(quick).result == "quick"


async def test_a_waiting_job_that_is_stopped_never_runs():
    from liteagent.jobs import CANCELLED
    store = JobStore(":memory:")
    waiting = store.create("task", "later")
    worker = Worker(store, lambda job: (_ for _ in ()).throw(AssertionError("must not run")))
    assert worker.cancel(waiting) is True
    assert store.get(waiting).error == CANCELLED
    assert await worker.run_once() is False
    assert worker.cancel("0" * 32) is False
