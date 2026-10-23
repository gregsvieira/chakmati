import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from .gate.base import Gate, Route
from .jobs import Job, JobStore
from .llm import ChatClient
from .research.tool import ResearchTool

SYSTEM_PROMPTS: dict[Route, str] = {
    Route.CHAT: "You are a concise, friendly assistant. Answer in the user's language.",
    Route.RESEARCH: (
        "You are a research assistant. Answer in the user's language. "
        "You have no web access yet: say what you know and what you could not verify."
    ),
    Route.CALENDAR: (
        "You are a calendar assistant, but the calendar is not connected. Say so briefly "
        "in the user's language."
    ),
    Route.WHATSAPP: (
        "You are a WhatsApp assistant, but WhatsApp is not connected. Say so briefly in the user's language."
    ),
    Route.TASK: (
        "You are a careful assistant for multi-step tasks. Answer in the user's "
        "language. You cannot run code or touch files yet: describe the steps."
    ),
}


CALENDAR_OFF = (
    "A integração com a agenda está desativada. No robô, ligue em Ajustes > Integrações; "
    "ou use LITEAGENT_CALENDAR_BACKEND=auto (ou macos / ics) e reinicie."
)


WHATSAPP_OFF = (
    "A integração com o WhatsApp está desativada. No robô, ligue em Ajustes > Integrações; "
    "ou use LITEAGENT_WHATSAPP_BACKEND=openwa (com o OpenWA em execução) e reinicie."
)


@dataclass(frozen=True)
class Reply:
    kind: str  # "answer" | "job"
    route: Route
    text: str | None = None
    job_id: str | None = None


def _messages(route: Route, text: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPTS[route]},
        {"role": "user", "content": text},
    ]


class Engine:
    def __init__(
        self,
        gate: Gate,
        llm: ChatClient,
        store: JobStore,
        researcher: ResearchTool | None = None,
        on_job_created: Callable[[], object] | None = None,
        calendar_assistant=None,
        whatsapp_assistant=None,
    ):
        self._gate = gate
        self._llm = llm
        self._store = store
        self._researcher = researcher
        self._on_job_created = on_job_created
        self._calendar = calendar_assistant
        self._whatsapp = whatsapp_assistant

    def _notify_job(self) -> None:
        if self._on_job_created is not None:
            self._on_job_created()

    async def handle(self, text: str) -> Reply:
        decision = await asyncio.to_thread(self._gate.classify, text)
        if not decision.route.is_slow:
            answer = await self._llm.chat(_messages(decision.route, text))
            return Reply("answer", decision.route, text=answer)
        job_id = self._store.create(decision.route.value, text)
        self._notify_job()
        return Reply("job", decision.route, job_id=job_id)

    async def _calendar_job(self, job: Job) -> str:
        if self._calendar is None:
            return CALENDAR_OFF
        return await self._calendar.handle(job.prompt)

    async def _whatsapp_job(self, job: Job) -> str:
        if self._whatsapp is None:
            return WHATSAPP_OFF
        return await self._whatsapp.handle(job.prompt)

    async def run_job(self, job: Job) -> str:
        if job.route == Route.CALENDAR.value:
            return await self._calendar_job(job)
        if job.route == Route.WHATSAPP.value:
            return await self._whatsapp_job(job)
        if self._researcher is not None and job.route == Route.RESEARCH.value:
            return (await self._researcher.answer(job.prompt)).render()
        return await self._llm.chat(_messages(Route(job.route), job.prompt))

    async def handle_stream(self, text: str) -> AsyncIterator[dict]:
        """Like `handle`, as a sequence of events: route, then either the reply as delta events
        followed by done (chat), or a single job event for slow work (follow it via the job stream)."""
        decision = await asyncio.to_thread(self._gate.classify, text)
        yield {"type": "route", "route": decision.route.value}
        if decision.route.is_slow:
            job_id = self._store.create(decision.route.value, text)
            self._notify_job()
            yield {"type": "job", "job_id": job_id, "route": decision.route.value}
            return
        parts: list[str] = []
        async for delta in self._llm.stream_chat(_messages(decision.route, text)):  # type: ignore[attr-defined]
            parts.append(delta)
            yield {"type": "delta", "text": delta}
        yield {"type": "done", "result": "".join(parts)}

    async def run_job_stream(self, job: Job) -> AsyncIterator[str]:
        """Streaming counterpart of `run_job`: yields the answer as it is produced."""
        if job.route == Route.CALENDAR.value:
            yield await self._calendar_job(job)
            return
        if job.route == Route.WHATSAPP.value:
            yield await self._whatsapp_job(job)
            return
        if self._researcher is not None and job.route == Route.RESEARCH.value:
            async for delta in self._researcher.stream_answer(job.prompt):
                yield delta
            return
        async for delta in self._llm.stream_chat(_messages(Route(job.route), job.prompt)):  # type: ignore[attr-defined]
            yield delta
