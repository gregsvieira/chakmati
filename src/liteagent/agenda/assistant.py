"""Natural-language front end for the calendar.

The model's only job is to turn the USER's request into a small JSON intent. Everything else is code:
events are looked up and formatted deterministically, so calendar text (titles, notes) is never sent to the
model and cannot steer it; and the assistant can only call `events`, `propose_create` and `propose_delete`,
never `approve`, so nothing is written without the user's explicit approval.
"""

import asyncio
import json
import re
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, tzinfo
from typing import Protocol

from ..llm import ChatClient
from .models import CalendarEvent, NewEvent

_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MAX_LISTED = 30
MAX_RANGE = timedelta(days=366)

SYSTEM = """You turn a calendar request into JSON. Reply with ONLY one JSON object, no prose.
Current date and time: {now} ({weekday}); the user's timezone offset is already part of that time.
Keys:
  "action": "list" (see events), "create" (add one), "delete" (remove one) or "other" (not about the calendar)
  "start", "end": local ISO 8601 like 2026-10-24T15:00:00, or null
  "title": what the event is, in the user's own words, capitalised (for "marque reunião de planejamento amanhã às 15h"
           the title is "Reunião de planejamento"); null ONLY when the user never said what the event is
  "location": or null; "notes": or null
  "all_day": true or false
  "match": for "delete", words from the title of the event to remove, or null
Resolve relative dates ("tomorrow", "next Friday") from the current date and time above.
If the user gives only a day of the month ("dia 30"), use the NEXT occurrence of that day: this month if it has not passed yet,
otherwise next month. Never choose a month that is more than one month away unless the user names it.
A bare statement without a verb ("feriado dia 12") is not a request to list events.
For "list" without a period use today (00:00 to 24:00). For "create" give "end" only if the user gave a duration or end.
Never invent a date or time the user did not say; use null instead. Do not put the date, time or place in the title."""

HELP = (
    "Não entendi o pedido de agenda. Exemplos: \"o que tenho amanhã?\", \"marque dentista dia 30 às 9h\", "
    "\"cancele a reunião de sexta\"."
)


class CalendarProposer(Protocol):
    """What the assistant may use. There is deliberately no approve/reject here."""

    def events(self, start: datetime, end: datetime) -> list[CalendarEvent]: ...

    def propose_create(self, new: NewEvent): ...

    def propose_delete(self, event: CalendarEvent): ...


@dataclass(frozen=True)
class Intent:
    action: str = "other"
    start: datetime | None = None
    end: datetime | None = None
    title: str | None = None
    all_day: bool = False
    location: str | None = None
    notes: str | None = None
    match: str | None = None


def _dt(value, tz: tzinfo | None) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=tz)


def _text(value) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def parse_intent(reply: str, now: datetime) -> Intent:
    """Extract the JSON object from the model's reply; anything unusable becomes action="other"."""
    first, last = reply.find("{"), reply.rfind("}")
    if first == -1 or last <= first:
        return Intent()
    try:
        data = json.loads(reply[first : last + 1])
    except json.JSONDecodeError:
        return Intent()
    if not isinstance(data, dict) or data.get("action") not in {"list", "create", "delete"}:
        return Intent()
    return Intent(
        action=data["action"],
        start=_dt(data.get("start"), now.tzinfo),
        end=_dt(data.get("end"), now.tzinfo),
        title=_text(data.get("title")),
        all_day=data.get("all_day") is True,
        location=_text(data.get("location")),
        notes=_text(data.get("notes")),
        match=_text(data.get("match")),
    )


def _norm(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


_BARE_DAY = re.compile(r"\bdia\s+(\d{1,2})\b(?!\s*(?:de\b|/|-|\.))", re.IGNORECASE)
_MONTH_WORDS = re.compile(
    r"\b(?:janeiro|fevereiro|marco|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro|mes)\b"
)


def resolve_bare_day(text: str, intent: Intent, now: datetime) -> Intent:
    """"dia 30" with no month means the NEXT occurrence of the 30th. The model gets this wrong (it put "dia 30"
    in the following month three times out of three), and a wrong month would be a silent mistake, so the date is
    computed here. Explicit dates ("dia 12 de novembro", "12/11", "mês que vem") are left alone."""
    match = _BARE_DAY.search(text)
    if intent.start is None or match is None or _MONTH_WORDS.search(_norm(text)):
        return intent
    day = int(match.group(1))
    if not 1 <= day <= 31:
        return intent
    year, month = now.year, now.month
    for _ in range(14):
        try:
            candidate = intent.start.replace(year=year, month=month, day=day)
        except ValueError:  # that month has no such day (e.g. the 31st of November)
            candidate = None
        if candidate is not None:
            upcoming = candidate.date() >= now.date() if intent.all_day else candidate >= now
            if upcoming:
                break
        month += 1
        if month > 12:
            year, month = year + 1, 1
    else:
        return intent
    if candidate == intent.start:
        return intent
    shift = candidate - intent.start
    return replace(intent, start=candidate, end=intent.end + shift if intent.end else None)


def _local(event: CalendarEvent, tz: tzinfo | None) -> CalendarEvent:
    if event.all_day or tz is None:
        return event
    return replace(event, start=event.start.astimezone(tz), end=event.end.astimezone(tz))


class CalendarAssistant:
    def __init__(self, llm: ChatClient, service: CalendarProposer, now=lambda: datetime.now().astimezone()):
        self._llm = llm
        self._service = service
        self._now = now

    async def _events(self, start: datetime, end: datetime, tz: tzinfo | None) -> list[CalendarEvent]:
        found = await asyncio.to_thread(self._service.events, start, end)
        return [_local(e, tz) for e in found]

    async def handle(self, text: str) -> str:
        now = self._now()
        system = SYSTEM.format(now=now.isoformat(timespec="seconds"), weekday=_WEEKDAYS[now.weekday()])
        reply = await self._llm.chat([{"role": "system", "content": system}, {"role": "user", "content": text}])
        intent = resolve_bare_day(text, parse_intent(reply, now), now)
        if intent.action == "list":
            return await self._list(intent, now)
        if intent.action == "create":
            return await self._create(intent, now)
        if intent.action == "delete":
            return await self._delete(intent, now)
        return HELP

    # ------------------------------------------------------------------ list
    def _range(self, intent: Intent, now: datetime, default_days: int) -> tuple[datetime, datetime]:
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = intent.start or today
        end = intent.end if intent.end and intent.end > start else start + timedelta(days=default_days)
        return start, min(end, start + MAX_RANGE)

    async def _list(self, intent: Intent, now: datetime) -> str:
        start, end = self._range(intent, now, 1)
        events = await self._events(start, end, now.tzinfo)
        head = f"Agenda de {start:%d/%m %H:%M} a {end:%d/%m %H:%M}:"
        if not events:
            return f"{head}\nNenhum evento nesse período."
        lines = [f"- {e.summary()}" for e in events[:MAX_LISTED]]
        if len(events) > MAX_LISTED:
            lines.append(f"... e mais {len(events) - MAX_LISTED} eventos.")
        return head + "\n" + "\n".join(lines)

    # ------------------------------------------------------------------ create
    async def _create(self, intent: Intent, now: datetime) -> str:
        if intent.start is None or intent.title is None:
            return "Quando será e qual o título do evento? Não consegui identificar a data, a hora ou o título."
        end = intent.end or intent.start + (timedelta(days=1) if intent.all_day else timedelta(hours=1))
        try:
            new = NewEvent(intent.title, intent.start, end, intent.all_day, intent.location or "", intent.notes or "")
        except ValueError as exc:
            return f"Não consegui montar o evento: {exc}."
        clashes = [e for e in await self._events(new.start, new.end, now.tzinfo) if not e.all_day][:3]
        action = self._service.propose_create(new)
        text = (
            f"Proposta {action.id} (aguardando a sua aprovação — nada foi gravado ainda):\n{action.summary}\n"
        )
        if clashes:
            text += "Atenção, conflita com: " + "; ".join(e.summary() for e in clashes) + "\n"
        return text + "Aprove ou rejeite na interface (POST /actions/{id}/approve ou /reject). Expira em 1 hora."

    # ------------------------------------------------------------------ delete
    async def _delete(self, intent: Intent, now: datetime) -> str:
        wanted = _norm(intent.match or intent.title or "")
        if not wanted:
            return "Qual evento você quer cancelar? Diga parte do título."
        start, end = self._range(intent, now, 30)
        matches = [e for e in await self._events(start, end, now.tzinfo) if wanted in _norm(e.title)]
        if not matches:
            return "Não encontrei nenhum evento com esse nome no período."
        if len(matches) > 1:
            listed = "\n".join(f"- {e.summary()}" for e in matches[:5])
            return f"Encontrei {len(matches)} eventos parecidos. Diga qual:\n{listed}"
        action = self._service.propose_delete(matches[0])
        return (
            f"Proposta {action.id} (aguardando a sua aprovação — nada foi apagado ainda):\n{action.summary}\n"
            "Aprove ou rejeite na interface (POST /actions/{id}/approve ou /reject). Expira em 1 hora."
        )
