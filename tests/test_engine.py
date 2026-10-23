import pytest

from liteagent.engine import SYSTEM_PROMPTS, Engine
from liteagent.gate.base import GateResult, Route
from liteagent.jobs import QUEUED, JobStore


class FakeGate:
    def __init__(self, route):
        self.route = route

    def classify(self, text):
        return GateResult(self.route, 1.0, "fake")


class FakeLLM:
    def __init__(self):
        self.calls = []

    async def chat(self, messages):
        self.calls.append(messages)
        return "llm says hi"


@pytest.fixture
def store():
    return JobStore(":memory:")


async def test_chat_is_answered_inline(store):
    llm = FakeLLM()
    reply = await Engine(FakeGate(Route.CHAT), llm, store).handle("olá")
    assert reply.kind == "answer"
    assert reply.route is Route.CHAT
    assert reply.text == "llm says hi"
    assert reply.job_id is None
    assert llm.calls == [
        [
            {"role": "system", "content": SYSTEM_PROMPTS[Route.CHAT]},
            {"role": "user", "content": "olá"},
        ]
    ]


@pytest.mark.parametrize("route", [Route.RESEARCH, Route.TASK])
async def test_slow_routes_become_jobs_without_calling_llm(store, route):
    llm = FakeLLM()
    reply = await Engine(FakeGate(route), llm, store).handle("do the thing")
    assert reply.kind == "job"
    assert reply.route is route
    assert reply.text is None
    job = store.get(reply.job_id)
    assert job.status == QUEUED
    assert job.route == route.value
    assert job.prompt == "do the thing"
    assert llm.calls == []


async def test_run_job_uses_route_specific_system_prompt(store):
    llm = FakeLLM()
    engine = Engine(FakeGate(Route.RESEARCH), llm, store)
    reply = await engine.handle("find x")
    job = store.get(reply.job_id)
    assert await engine.run_job(job) == "llm says hi"
    assert llm.calls[0][0] == {
        "role": "system",
        "content": SYSTEM_PROMPTS[Route.RESEARCH],
    }
    assert llm.calls[0][1] == {"role": "user", "content": "find x"}
