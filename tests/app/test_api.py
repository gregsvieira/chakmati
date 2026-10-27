import time

import pytest
from fastapi.testclient import TestClient

from chakmati.app.api import create_app
from chakmati.shared.config import Settings
from chakmati.app.engine import Engine
from chakmati.shared.gate.base import GateResult, Route
from chakmati.shared.jobs import JobStore, Worker
from chakmati.main import build_app


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


import asyncio as _asyncio
import json as _json


class StreamLLM:
    """Streams a fixed reply in pieces, with a tiny pause so the SSE poller sees partial text."""

    def __init__(self, deltas=("Ol", "á", ", mundo")):
        self.deltas = list(deltas)

    async def chat(self, messages):
        return "".join(self.deltas)

    async def stream_chat(self, messages):
        for d in self.deltas:
            await _asyncio.sleep(0.03)
            yield d


def sse_events(response):
    return [_json.loads(line[len("data: "):]) for line in response.iter_lines() if line.startswith("data: ")]


@pytest.fixture
def stream_engine(store):
    return Engine(FakeGate(), StreamLLM(), store)


def stream_app(stream_engine, store):
    worker = Worker(store, None, poll_seconds=0.01, stream_handler=stream_engine.run_job_stream, flush_interval=0)
    return create_app(stream_engine, store, worker)


def test_job_response_exposes_partial(engine, store):
    client = TestClient(create_app(engine, store))
    job_id = client.post("/message", json={"text": "search x"}).json()["job_id"]
    assert client.get(f"/jobs/{job_id}").json()["partial"] == ""


def test_job_stream_sends_deltas_then_done(stream_engine, store):
    with TestClient(stream_app(stream_engine, store)) as client:
        job_id = client.post("/message", json={"text": "search python"}).json()["job_id"]
        with client.stream("GET", f"/jobs/{job_id}/stream") as response:
            assert response.headers["content-type"].startswith("text/event-stream")
            events = sse_events(response)
    types = [e["type"] for e in events]
    assert types[0] == "status" and types[-1] == "done"
    assert "delta" in types
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "Olá, mundo"
    assert events[-1] == {"type": "done", "result": "Olá, mundo"}


def test_job_stream_unknown_job_is_404(stream_engine, store):
    with TestClient(stream_app(stream_engine, store)) as client:
        assert client.get("/jobs/nope/stream").status_code == 404


def test_job_stream_reports_failure(store):
    class Boom:
        async def stream_chat(self, messages):
            yield "par"
            raise RuntimeError("model died")

        async def chat(self, messages):
            raise RuntimeError("model died")

    eng = Engine(FakeGate(), Boom(), store)
    with TestClient(stream_app(eng, store)) as client:
        job_id = client.post("/message", json={"text": "search x"}).json()["job_id"]
        with client.stream("GET", f"/jobs/{job_id}/stream") as response:
            events = sse_events(response)
    assert events[-1] == {"type": "error", "error": "RuntimeError: model died"}


def test_message_stream_chat_streams_inline(stream_engine, store):
    with TestClient(stream_app(stream_engine, store)) as client:
        with client.stream("POST", "/message/stream", json={"text": "olá"}) as response:
            events = sse_events(response)
    assert events[0] == {"type": "route", "route": "chat"}
    assert "".join(e["text"] for e in events if e["type"] == "delta") == "Olá, mundo"
    assert events[-1] == {"type": "done", "result": "Olá, mundo"}


def test_message_stream_slow_route_follows_the_job_to_the_end(stream_engine, store):
    with TestClient(stream_app(stream_engine, store)) as client:
        with client.stream("POST", "/message/stream", json={"text": "search python"}) as response:
            events = sse_events(response)
    types = [e["type"] for e in events]
    assert types[:2] == ["route", "job"] and events[1]["route"] == "research"
    assert types[-1] == "done" and events[-1]["result"] == "Olá, mundo"
    assert "delta" in types


def test_message_stream_rejects_empty_text(stream_engine, store):
    with TestClient(stream_app(stream_engine, store)) as client:
        assert client.post("/message/stream", json={"text": ""}).status_code == 422
