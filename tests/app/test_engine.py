import pytest

from chakmati.app.engine import SYSTEM_PROMPTS, Engine
from chakmati.shared.gate.base import GateResult, Route
from chakmati.shared.jobs import QUEUED, JobStore


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
    system = llm.calls[0][0]
    assert system["role"] == "system" and system["content"].startswith(SYSTEM_PROMPTS[Route.RESEARCH])
    assert "Hoje é" in system["content"] and "internet" in system["content"]  # a research job knows the date, and admits it cannot search
    assert llm.calls[0][1] == {"role": "user", "content": "find x"}


class StreamingLLM(FakeLLM):
    def __init__(self, deltas=("Ol", "á")):
        super().__init__()
        self.deltas = list(deltas)

    async def stream_chat(self, messages):
        self.calls.append(messages)
        for d in self.deltas:
            yield d


async def collect(aiter):
    return [e async for e in aiter]


async def test_handle_stream_chat_emits_route_deltas_and_done(store):
    llm = StreamingLLM()
    events = await collect(Engine(FakeGate(Route.CHAT), llm, store).handle_stream("olá"))
    assert events == [
        {"type": "route", "route": "chat"},
        {"type": "delta", "text": "Ol"},
        {"type": "delta", "text": "á"},
        {"type": "done", "result": "Olá"},
    ]
    assert llm.calls[0][0]["content"] == SYSTEM_PROMPTS[Route.CHAT]


@pytest.mark.parametrize("route", [Route.RESEARCH, Route.TASK])
async def test_handle_stream_slow_route_emits_job_event_only(store, route):
    events = await collect(Engine(FakeGate(route), StreamingLLM(), store).handle_stream("faça"))
    assert [e["type"] for e in events] == ["route", "job"]
    assert events[1]["route"] == route.value and store.get(events[1]["job_id"]).prompt == "faça"


async def test_run_job_stream_uses_llm_stream_or_researcher_stream(store):
    llm = StreamingLLM(["a", "b"])
    engine = Engine(FakeGate(Route.TASK), llm, store)
    job_id = store.create("task", "p")
    assert await collect(engine.run_job_stream(store.get(job_id))) == ["a", "b"]

    class R:
        async def stream_answer(self, query, today=None, now=None):
            yield f"web:{query}"

    engine2 = Engine(FakeGate(Route.RESEARCH), llm, store, researcher=R())
    rid = store.create("research", "q")
    assert await collect(engine2.run_job_stream(store.get(rid))) == ["web:q"]


async def test_on_job_created_is_called_for_slow_routes_only(store):
    calls = []
    slow = Engine(FakeGate(Route.TASK), StreamingLLM(), store, on_job_created=lambda: calls.append(1))
    await slow.handle("faça")
    await collect(slow.handle_stream("faça de novo"))
    assert calls == [1, 1]
    chat = Engine(FakeGate(Route.CHAT), StreamingLLM(), store, on_job_created=lambda: calls.append(2))
    await chat.handle("oi")
    assert calls == [1, 1]


class FakeAssistant:
    def __init__(self):
        self.asked = []

    async def handle(self, text):
        self.asked.append(text)
        return "agenda: 2 eventos"


async def test_calendar_job_uses_the_assistant_and_never_the_plain_llm(store):
    llm, assistant = StreamingLLM(), FakeAssistant()
    engine = Engine(FakeGate(Route.CALENDAR), llm, store, calendar_assistant=assistant)
    reply = await engine.handle("o que tenho amanhã?")
    assert reply.kind == "job" and reply.route is Route.CALENDAR
    job = store.get(reply.job_id)
    assert await engine.run_job(job) == "agenda: 2 eventos"
    assert await collect(engine.run_job_stream(job)) == ["agenda: 2 eventos"]
    assert assistant.asked == ["o que tenho amanhã?"] * 2 and llm.calls == []


async def test_calendar_job_without_an_assistant_says_the_feature_is_off(store):
    llm = StreamingLLM()
    engine = Engine(FakeGate(Route.CALENDAR), llm, store)
    job = store.get((await engine.handle("marque reunião")).job_id)
    text = await engine.run_job(job)
    assert "desativ" in text.lower() and "CHAKMATI_CALENDAR_BACKEND" in text and llm.calls == []
    assert "".join(await collect(engine.run_job_stream(job))) == text


async def test_whatsapp_job_uses_the_assistant_and_never_the_plain_llm(store):
    llm, assistant = StreamingLLM(), FakeAssistant()
    engine = Engine(FakeGate(Route.WHATSAPP), llm, store, whatsapp_assistant=assistant)
    job = store.get((await engine.handle("tenho mensagens novas?")).job_id)
    assert await engine.run_job(job) == "agenda: 2 eventos"
    assert await collect(engine.run_job_stream(job)) == ["agenda: 2 eventos"]
    assert assistant.asked == ["tenho mensagens novas?"] * 2 and llm.calls == []


async def test_whatsapp_job_without_an_assistant_says_the_feature_is_off(store):
    engine = Engine(FakeGate(Route.WHATSAPP), StreamingLLM(), store)
    job = store.get((await engine.handle("manda oi pro João")).job_id)
    text = await engine.run_job(job)
    assert "desativ" in text.lower() and "CHAKMATI_WHATSAPP_BACKEND" in text
    assert "".join(await collect(engine.run_job_stream(job))) == text


class PendingWhatsApp:
    def __init__(self):
        self.waiting_for = "Maria Souza"

    def awaiting_choice(self, text):
        return text == self.waiting_for

    async def handle(self, text):
        return f"continued with {text}"


async def test_an_answer_to_a_pending_whatsapp_question_goes_back_to_the_whatsapp_assistant(store):
    engine = Engine(FakeGate(Route.CHAT), FakeLLM(), store, whatsapp_assistant=PendingWhatsApp())
    reply = await engine.handle("Maria Souza")  # the gate alone would call this plain chat
    assert reply.kind == "job" and reply.route is Route.WHATSAPP
    assert store.get(reply.job_id).prompt == "Maria Souza"
    other = await engine.handle("olá")
    assert other.kind == "answer" and other.route is Route.CHAT


async def test_the_stream_also_routes_a_pending_answer_to_whatsapp(store):
    engine = Engine(FakeGate(Route.CHAT), FakeLLM(), store, whatsapp_assistant=PendingWhatsApp())
    events = [e async for e in engine.handle_stream("Maria Souza")]
    assert events[0] == {"type": "route", "route": "whatsapp"} and events[1]["type"] == "job"
