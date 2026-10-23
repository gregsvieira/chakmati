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
