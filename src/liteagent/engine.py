import asyncio
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
    Route.TASK: (
        "You are a careful assistant for multi-step tasks. Answer in the user's "
        "language. You cannot run code or touch files yet: describe the steps."
    ),
}


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
    ):
        self._gate = gate
        self._llm = llm
        self._store = store
        self._researcher = researcher

    async def handle(self, text: str) -> Reply:
        decision = await asyncio.to_thread(self._gate.classify, text)
        if not decision.route.is_slow:
            answer = await self._llm.chat(_messages(decision.route, text))
            return Reply("answer", decision.route, text=answer)
        job_id = self._store.create(decision.route.value, text)
        return Reply("job", decision.route, job_id=job_id)

    async def run_job(self, job: Job) -> str:
        if self._researcher is not None and job.route == Route.RESEARCH.value:
            return (await self._researcher.answer(job.prompt)).render()
        return await self._llm.chat(_messages(Route(job.route), job.prompt))
