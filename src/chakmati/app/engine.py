import asyncio
import random
import re
import time
from datetime import datetime
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from chakmati.features.automations.confirm import verdict
from chakmati.features.chat import patriot
from chakmati.features.chat.canned import canned_answer
from chakmati.shared import personality as personalities
from chakmati.shared import pronouns as pronoun_sets
from chakmati.shared.persona import AWAKE_SECONDS, PERSONA, wake_reply
from chakmati.shared.timeguard import calendar_facts, needs_today, needs_web, today_line
from chakmati.shared.gate.base import Gate, Route
from chakmati.shared.jobs import Job, JobStore
from chakmati.shared.llm import ChatClient
from chakmati.features.research.tool import ResearchTool

_ROUTE_PROMPTS: dict[Route, str] = {
    Route.CHAT: "You are a concise, friendly assistant. Answer in the user's language. Never invent rules, permissions or security policies (you do not have a policy against visiting sites or using accounts): if a request needs a tool you do not have in this chat, say what you would need.",
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
    Route.COMPUTER: "You can act on the computer, but that is not available. Say so briefly in the user's language.",
    Route.BROWSER: "You can use a web browser, but it is not available. Say so briefly in the user's language.",
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
COMPUTER_OFF = "As ações no computador estão desativadas neste motor."
HOME_OFF = "A casa inteligente está desativada. Configure o Home Assistant (CHAKMATI_HOME_BACKEND=homeassistant, URL e token)."
BROWSER_OFF = ("O navegador automático do Chakmati não está ligado, então não consigo navegar sozinho. Para abrir uma página no SEU navegador, diga o endereço ou o nome do site, "
               "por exemplo: \"abre https://www.stremio.com/downloads\". (Para ligar o navegador automático: CHAKMATI_BROWSER_BACKEND=chrome e uv sync --extra browser.)")
AUTOMATION_OFF = "As automações estão desativadas neste motor."

CALENDAR_OFF = (
    "A integração com a agenda está desativada. No robô, ligue em Ajustes > Integrações; "
    "ou use CHAKMATI_CALENDAR_BACKEND=auto (ou macos / ics) e reinicie."
)


WHATSAPP_OFF = (
    "A integração com o WhatsApp está desativada. No robô, ligue em Ajustes > Integrações; "
    "ou use CHAKMATI_WHATSAPP_BACKEND=openwa (com o OpenWA em execução) e reinicie."
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
        computer_assistant=None,
        computer_service=None,
        browser_agent=None,
        personality: str = personalities.DEFAULT,
        pronouns: str = pronoun_sets.DEFAULT,
        rng: random.Random | None = None,
        typing_delay: float = 0.012,
        now: Callable[[], float] = time.time,
        clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    ):
        self._personality = personalities.normalize(personality)  # the regional way of speaking added to short chat answers (shared/personality.py)
        self._pronouns = pronoun_sets.normalize(pronouns)  # how the person is addressed: picks the words code adds, and one line for the model
        self._rng = rng or random.Random()
        self._typing_delay = typing_delay  # seconds between the pieces of a fixed answer: it is typed out, not dropped whole
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
        self._computer = computer_assistant
        self._computer_service = computer_service
        self._browser = browser_agent

    @property
    def personality(self) -> str:
        return self._personality

    def set_personality(self, personality_id: str) -> bool:
        """Changes the way of speaking at once (no restart); False, and nothing changes, for an unknown one."""
        if not personalities.valid(personality_id):
            return False
        self._personality = personality_id
        return True

    @property
    def pronouns(self) -> str:
        return self._pronouns

    def set_pronouns(self, pronouns_id: str) -> bool:
        """Changes how the person is addressed at once; False, and nothing changes, for an unknown one."""
        if not pronoun_sets.valid(pronouns_id):
            return False
        self._pronouns = pronouns_id
        return True

    def _flavored(self, answer: str) -> str:
        return personalities.flavor(answer, self._personality, self._rng, self._pronouns)

    def _msgs(self, route: Route, text: str, today: str | None = None, offline: bool = False) -> list[dict[str, str]]:
        """The model's messages, plus (only when the person said their pronouns) the one line that tells it how to address them."""
        messages = _messages(route, text, today, offline)
        if line := pronoun_sets.prompt_line(self._pronouns):
            messages[0]["content"] += f" {line}"
        return messages

    async def _flavored_stream(self, deltas: AsyncIterator[str]) -> AsyncIterator[str]:
        """The model's pieces as they come, except that a short answer is held until it is complete, so the opening and closing can go around it
        and are then typed out. The moment it turns out to be long (or a list) the held text is released and the rest streams untouched."""
        if self._personality == personalities.DEFAULT:
            async for delta in deltas:
                yield delta
            return
        held: list[str] = []
        released = False
        async for delta in deltas:
            if released:
                yield delta
                continue
            held.append(delta)
            if not personalities.eligible("".join(held)):
                released = True
                yield "".join(held)
        if released:
            return
        text = "".join(held)
        styled = self._flavored(text)
        if styled == text:
            yield text
            return
        for piece in re.findall(r"\S+\s*|\s+", styled):
            yield piece
            if self._typing_delay:
                await asyncio.sleep(self._typing_delay)

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
        greeting = wake_reply(text, prompts=personalities.listening_prompts(self._personality, self._pronouns))
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
        for service in (self._automation_service, self._home_service, self._computer_service):
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

    async def _plan_text(self, job: Job) -> str:
        """The steps of this job, shown first ("Plano: 1. ... 2. ..."), or "" when the job is too simple to need one. Never stops the job."""
        try:
            if job.route == Route.COMPUTER.value and self._computer is not None and hasattr(self._computer, "plan"):
                steps = await self._computer.plan(job.prompt)
            elif job.route == Route.BROWSER.value and self._browser is not None:
                steps = self._browser.plan(job.prompt)
            else:
                steps = None
        except Exception:
            steps = None
        if not steps:
            return ""
        return "Plano:\n" + "\n".join(f"{i}. {step}" for i, step in enumerate(steps, 1)) + "\n\n"

    async def _computer_job(self, job: Job) -> str:
        if self._computer is None:
            return COMPUTER_OFF
        result = await self._computer.handle(job.prompt)
        if "Confirma?" in result:
            self._awake_until = self._now() + CONFIRM_SECONDS
        return result

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

    async def _patriotic(self, text: str, answer: patriot.Patriotic) -> AsyncIterator[str]:
        """The pieces of a patriotic answer as they are typed: the fixed parts word by word, the model's part as the model writes it."""
        for part in answer.parts:
            if part == patriot.MODEL:
                if hasattr(self._llm, "stream_chat"):
                    async for delta in self._llm.stream_chat(self._msgs(Route.CHAT, text)):  # type: ignore[attr-defined]
                        yield delta
                else:
                    yield await self._llm.chat(self._msgs(Route.CHAT, text))
                continue
            for piece in re.findall(r"\S+\s*|\s+", part):
                yield piece
                if self._typing_delay:
                    await asyncio.sleep(self._typing_delay)

    async def handle(self, text: str) -> Reply:
        fixed = self._wake(text) or await self._confirmation(text) or canned_answer(text)
        if fixed is not None:
            return Reply("answer", Route.CHAT, text=fixed)
        if (patriotic := patriot.match(text)) is not None:
            return Reply("answer", Route.CHAT, text="".join([piece async for piece in self._patriotic(text, patriotic)]).strip())
        route, today, offline = await self._plan(text)
        if not route.is_slow:
            answer = await self._llm.chat(self._msgs(route, text, today, offline))
            return Reply("answer", route, text=self._flavored(answer))
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
        if job.route in (Route.COMPUTER.value, Route.BROWSER.value):
            return "".join([piece async for piece in self.run_job_stream(job)])
        now = self._clock()
        today = today_line(now)  # research answers are about "now": they always know what day it is
        if self._researcher is not None and job.route == Route.RESEARCH.value:
            return (await self._researcher.answer(job.prompt, today=today, now=now)).render()
        offline = job.route == Route.RESEARCH.value  # a research job with search switched off
        return await self._llm.chat(self._msgs(Route(job.route), job.prompt, today if offline else None, offline))

    async def handle_stream(self, text: str) -> AsyncIterator[dict]:
        """Like `handle`, as a sequence of events: route, then either the reply as delta events
        followed by done (chat), or a single job event for slow work (follow it via the job stream)."""
        fixed = self._wake(text) or await self._confirmation(text) or canned_answer(text)
        if fixed is not None:
            yield {"type": "route", "route": Route.CHAT.value}
            yield {"type": "delta", "text": fixed}
            yield {"type": "done", "result": fixed}
            return
        if (patriotic := patriot.match(text)) is not None:
            yield {"type": "route", "route": Route.CHAT.value}
            parts: list[str] = []
            async for piece in self._patriotic(text, patriotic):
                parts.append(piece)
                yield {"type": "delta", "text": piece}
            yield {"type": "done", "result": "".join(parts).strip()}
            return
        route, today, offline = await self._plan(text)
        yield {"type": "route", "route": route.value}
        if route.is_slow:
            job_id = self._store.create(route.value, text)
            self._notify_job()
            yield {"type": "job", "job_id": job_id, "route": route.value}
            return
        parts: list[str] = []
        async for delta in self._flavored_stream(self._llm.stream_chat(self._msgs(route, text, today, offline))):  # type: ignore[attr-defined]
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
        if job.route == Route.COMPUTER.value:
            if plan := await self._plan_text(job):
                yield plan  # first thing the person sees: what is about to be done, and with which tool or model
            yield await self._computer_job(job)
            return
        if job.route == Route.BROWSER.value:
            if self._browser is None:
                yield BROWSER_OFF
                return
            if plan := await self._plan_text(job):
                yield plan
            async for piece in self._browser.run(job.id, job.prompt):
                yield piece
            return
        now = self._clock()
        today = today_line(now)
        if self._researcher is not None and job.route == Route.RESEARCH.value:
            async for delta in self._researcher.stream_answer(job.prompt, today=today, now=now):
                yield delta
            return
        offline = job.route == Route.RESEARCH.value
        async for delta in self._llm.stream_chat(self._msgs(Route(job.route), job.prompt, today if offline else None, offline)):  # type: ignore[attr-defined]
            yield delta
