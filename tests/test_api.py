import time

import pytest
from fastapi.testclient import TestClient

from liteagent.api import create_app
from liteagent.config import Settings
from liteagent.engine import Engine
from liteagent.gate.base import GateResult, Route
from liteagent.jobs import JobStore, Worker
from liteagent.main import build_app


class FakeGate:
    def classify(self, text):
        route = Route.RESEARCH if "search" in text else Route.CHAT
        return GateResult(route, 1.0, "fake")


class FakeLLM:
    async def chat(self, messages):
        return "pong"


@pytest.fixture
def store():
    return JobStore(":memory:")


@pytest.fixture
def engine(store):
    return Engine(FakeGate(), FakeLLM(), store)


def test_health(engine, store):
    client = TestClient(create_app(engine, store))
    assert client.get("/health").json() == {"status": "ok"}


def test_chat_message_answers_inline(engine, store):
    client = TestClient(create_app(engine, store))
    body = client.post("/message", json={"text": "olá"}).json()
    assert body == {"kind": "answer", "route": "chat", "text": "pong", "job_id": None}


def test_slow_message_returns_job_and_job_is_queued(engine, store):
    client = TestClient(create_app(engine, store))
    body = client.post("/message", json={"text": "search python"}).json()
    assert body["kind"] == "job" and body["route"] == "research"
    job = client.get(f"/jobs/{body['job_id']}").json()
    assert job["status"] == "queued"
    assert job["result"] is None


def test_unknown_job_is_404(engine, store):
    assert TestClient(create_app(engine, store)).get("/jobs/nope").status_code == 404


@pytest.mark.parametrize("payload", [{"text": ""}, {}, {"text": "x" * 8001}])
def test_invalid_message_is_422(engine, store, payload):
    client = TestClient(create_app(engine, store))
    assert client.post("/message", json=payload).status_code == 422


def test_worker_completes_job_in_background(engine, store):
    worker = Worker(store, engine.run_job, poll_seconds=0.01)
    with TestClient(create_app(engine, store, worker)) as client:
        job_id = client.post("/message", json={"text": "search python"}).json()["job_id"]
        job = None
        for _ in range(100):
            job = client.get(f"/jobs/{job_id}").json()
            if job["status"] == "done":
                break
            time.sleep(0.02)
    assert job["status"] == "done"
    assert job["result"] == "pong"


def test_build_app_smoke():
    app = build_app(Settings(db_path=":memory:"))
    assert TestClient(app).get("/health").status_code == 200


def test_on_startup_hook_runs_in_the_background(engine, store):
    called = []

    async def hook():
        called.append(True)

    with TestClient(create_app(engine, store, on_startup=hook)):
        for _ in range(50):
            if called:
                break
            time.sleep(0.02)
    assert called == [True]
