import asyncio
import time
from datetime import datetime
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from .automations.confirm import verdict
from .canned import canned_answer
from .persona import AWAKE_SECONDS, PERSONA, wake_reply
from .timeguard import calendar_facts, needs_today, needs_web, today_line
from .gate.base import Gate, Route
from .jobs import Job, JobStore
from .llm import ChatClient
from .research.tool import ResearchTool

_ROUTE_PROMPTS: dict[Route, str] = {
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
    Route.HOME: "You control a smart home, but it is not connected. Say so briefly in the user's language.",
    Route.AUTOMATION: "You help create automations, but they are not available. Say so briefly in the user's language.",
    Route.TASK: (
        "You are a careful assistant for multi-step tasks. Answer in the user's "
        "language. You cannot run code or touch files yet: describe the steps."
    ),
}

# Every chat call starts with who the assistant is, so it never leaves the character (or the language).
SYSTEM_PROMPTS: dict[Route, str] = {route: f"{PERSONA} {text}" for route, text in _ROUTE_PROMPTS.items()}


CONFIRM_SECONDS = 30.0
HOME_OFF = "A casa inteligente está desativada. Configure o Home Assistant (LITEAGENT_HOME_BACKEND=homeassistant, URL e token)."
AUTOMATION_OFF = "As automações estão desativadas neste motor."

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


OFFLINE_NOTE = (
    "Você não tem acesso à internet agora e não conhece fatos recentes: se a resposta depender deles, diga que não sabe, "
    "sem inventar."
)


def _messages(route: Route, text: str, today: str | None = None, offline: bool = False) -> list[dict[str, str]]:
    """`today` is the line with today's date, added when the question depends on it; `offline` says the model cannot search."""
    system = SYSTEM_PROMPTS[route]
    if today:
        system += f" {today} Use estas informações de data, já calculadas, sem recalcular nem inventar datas."
    if offline:
        system += f" {OFFLINE_NOTE}"
    return [{"role": "system", "content": system}, {"role": "user", "content": text}]


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
        automation_assistant=None,
        automation_service=None,
        home_assistant=None,
        home_service=None,
        now: Callable[[], float] = time.time,
        clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    ):
        self._now = now
        self._clock = clock
        self._awake_until = 0.0
        self._gate = gate
        self._llm = llm
        self._store = store
        self._researcher = researcher
        self._on_job_created = on_job_created
        self._calendar = calendar_assistant
        self._whatsapp = whatsapp_assistant
        self._automation = automation_assistant
        self._automation_service = automation_service
        self._home = home_assistant
        self._home_service = home_service

    def _notify_job(self) -> None:
        if self._on_job_created is not None:
            self._on_job_created()

    @property
    def awake(self) -> bool:
        """True after a wake phrase, while the assistant waits for the command."""
        return self._now() < self._awake_until

    @property
    def awake_for(self) -> float:
        """Seconds left of the wait for a command (0 when asleep)."""
        return max(0.0, self._awake_until - self._now())

    def _wake(self, text: str) -> str | None:
        greeting = wake_reply(text)
        self._awake_until = self._now() + AWAKE_SECONDS if greeting else 0.0  # any other message is the command: waiting ends
        return greeting

    def _awaiting_whatsapp_choice(self, text: str) -> bool:
        """The text answers "which Maria?", a question the WhatsApp assistant just asked: it must go back to it."""
        return self._whatsapp is not None and hasattr(self._whatsapp, "awaiting_choice") and self._whatsapp.awaiting_choice(text)

    def expect_answer(self, seconds: float = CONFIRM_SECONDS) -> None:
        """A yes/no/redo is expected: the microphone listens without a wake phrase for a while."""
        self._awake_until = self._now() + seconds

    def _awaiting_automation_choice(self, text: str) -> bool:
        return self._automation is not None and hasattr(self._automation, "awaiting_choice") and self._automation.awaiting_choice(text)

    async def _confirmation(self, text: str) -> str | None:
        """A short yes/no while something waits for confirmation (a new automation, opening the house): does or drops it."""
        for service in (self._automation_service, self._home_service):
            pending = service.pending_confirmation() if service is not None else None
            answer = verdict(text) if pending is not None else None
            if answer is None:
                continue
            if answer == "yes":
                done = await service.aapprove(pending.id)
                return done.result or done.error or "Feito."
            service.reject(pending.id)
            return getattr(service, "cancel_text", "Certo, não criei a automação.")
        return None

    async def _home_job(self, job: Job) -> str:
        if self._home is None:
            return HOME_OFF
        result = await self._home.handle(job.prompt)
        if "Confirma?" in result:
            self._awake_until = self._now() + CONFIRM_SECONDS
        return result

    async def _automation_job(self, job: Job) -> str:
        if self._automation is None:
            return AUTOMATION_OFF
        result = await self._automation.handle(job.prompt)
        if "Confirma?" in result or "Qual destes" in result or "?" in result[-3:]:
            self._awake_until = self._now() + CONFIRM_SECONDS  # an answer is expected: listen without a wake phrase
        return result

    async def _plan(self, text: str) -> tuple[Route, str | None, bool]:
        """The route, plus today's date when the question needs it, plus whether the model must admit it cannot search."""
        if self._awaiting_whatsapp_choice(text):
            return Route.WHATSAPP, None, False
        if self._awaiting_automation_choice(text):
            return Route.AUTOMATION, None, False
        route = (await asyncio.to_thread(self._gate.classify, text)).route
        now = self._clock()
        today, offline = None, False
        if route in (Route.CHAT, Route.RESEARCH):
            if needs_web(text, now):  # events and recent facts: look them up, never let the model guess
                if self._researcher is not None:
                    route = Route.RESEARCH
                else:
                    today, offline = today_line(now), True
            elif route is Route.CHAT and needs_today(text):  # the model can solve it once it knows the date, and the sums are done here
                today = " ".join([today_line(now), *calendar_facts(text, now)])
        return route, today, offline

    async def handle(self, text: str) -> Reply:
        fixed = self._wake(text) or await self._confirmation(text) or canned_answer(text)
        if fixed is not None:
            return Reply("answer", Route.CHAT, text=fixed)
        route, today, offline = await self._plan(text)
        if not route.is_slow:
            answer = await self._llm.chat(_messages(route, text, today, offline))
            return Reply("answer", route, text=answer)
        job_id = self._store.create(route.value, text)
        self._notify_job()
        return Reply("job", route, job_id=job_id)

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
        if job.route == Route.AUTOMATION.value:
            return await self._automation_job(job)
        if job.route == Route.HOME.value:
            return await self._home_job(job)
        now = self._clock()
        today = today_line(now)  # research answers are about "now": they always know what day it is
        if self._researcher is not None and job.route == Route.RESEARCH.value:
            return (await self._researcher.answer(job.prompt, today=today, now=now)).render()
        offline = job.route == Route.RESEARCH.value  # a research job with search switched off
        return await self._llm.chat(_messages(Route(job.route), job.prompt, today if offline else None, offline))

    async def handle_stream(self, text: str) -> AsyncIterator[dict]:
        """Like `handle`, as a sequence of events: route, then either the reply as delta events
        followed by done (chat), or a single job event for slow work (follow it via the job stream)."""
        fixed = self._wake(text) or await self._confirmation(text) or canned_answer(text)
        if fixed is not None:
            yield {"type": "route", "route": Route.CHAT.value}
            yield {"type": "delta", "text": fixed}
            yield {"type": "done", "result": fixed}
            return
        route, today, offline = await self._plan(text)
        yield {"type": "route", "route": route.value}
        if route.is_slow:
            job_id = self._store.create(route.value, text)
            self._notify_job()
            yield {"type": "job", "job_id": job_id, "route": route.value}
            return
        parts: list[str] = []
        async for delta in self._llm.stream_chat(_messages(route, text, today, offline)):  # type: ignore[attr-defined]
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
        if job.route == Route.AUTOMATION.value:
            yield await self._automation_job(job)
            return
        if job.route == Route.HOME.value:
            yield await self._home_job(job)
            return
        now = self._clock()
        today = today_line(now)
        if self._researcher is not None and job.route == Route.RESEARCH.value:
            async for delta in self._researcher.stream_answer(job.prompt, today=today, now=now):
                yield delta
            return
        offline = job.route == Route.RESEARCH.value
        async for delta in self._llm.stream_chat(_messages(Route(job.route), job.prompt, today if offline else None, offline)):  # type: ignore[attr-defined]
            yield delta
