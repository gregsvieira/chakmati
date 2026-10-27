"""Natural-language front end for creating automations.

The model's only job is to turn the PERSON's request into a small JSON intent. Everything else is code: the cron expression is
built here from a time and days, the recipient is found by matching the name against the chat list (never by the model), the
reply text is the person's own words, and nothing is created: the result is a PROPOSAL that has to be confirmed (in the app or
by saying yes). Received messages and web pages never reach this module.
"""

import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass

from chakmati.shared.approvals import Action
from chakmati.shared.llm import ChatClient
from chakmati.features.whatsapp.assistant import pick_candidate, resolve_chat
from chakmati.features.whatsapp.models import Chat
from chakmati.features.automations.models import SpecError, describe, parse_spec
from chakmati.features.automations.service import AutomationError, AutomationService

SYSTEM = """You turn a request to create or list automations into JSON. Reply with ONLY one JSON object, no prose.
Keys:
  "action": "create" (make an automation), "list" (show the automations that exist) or "other"
  "name": a short name for it, or null
  "when": "message" (when someone writes to the user on WhatsApp), "time" (at a time of day) or "event" (before or when a calendar event starts)
  "time": for "time", the hour as "HH:MM" in 24 hours; otherwise null
  "days": for "time": "daily", "weekdays" (Monday to Friday), "weekend", or a list of weekday numbers 0-6 (0 = Sunday); otherwise null
  "event_words": for "event", words the event title contains; otherwise null
  "minutes_before": for "event", how many minutes before it starts (0 = when it starts); otherwise null
  "include_groups": true only if the user explicitly wants group chats included, otherwise false
  "cooldown_minutes": only if the user said how often to reply to the same person, otherwise null
  "reply_mode": "voice" if the user wants an audio / recorded / voice reply, otherwise "text"
  "reply_text": the reply EXACTLY as the user wants it written (do not add, remove or reword anything), or null
  "to": for "time" and "event", the name of the person or group that receives the message; null for "message" (the reply goes to whoever wrote)
Never invent anything the user did not say."""

HELP = ("Não entendi o pedido de automação. Exemplos: \"sempre que alguém me escrever no WhatsApp, responda: estou ocupado\", "
        "\"todo dia útil às 9h mande bom dia para o João\", \"5 minutos antes de toda reunião avise a Maria\".")
PENDING_SECONDS = 300.0
_TIME = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")
_DAYS = {"daily": "*", "weekdays": "1-5", "weekend": "0,6"}
_ACTIONS = {"create", "list"}


def cron_for(time_text, days) -> str | None:
    """"09:00" + "weekdays" -> "0 9 * * 1-5". None when the time or the days make no sense."""
    match = _TIME.match(time_text) if isinstance(time_text, str) else None
    if not match or int(match.group(1)) > 23 or int(match.group(2)) > 59:
        return None
    if days is None:
        field = "*"
    elif isinstance(days, str) and days in _DAYS:
        field = _DAYS[days]
    elif isinstance(days, list) and days and all(isinstance(d, int) and not isinstance(d, bool) and 0 <= d <= 6 for d in days):
        field = ",".join(str(d) for d in sorted(set(days)))
    else:
        return None
    return f"{int(match.group(2))} {int(match.group(1))} * * {field}"


@dataclass(frozen=True)
class Intent:
    action: str = "other"
    name: str | None = None
    when: str | None = None
    time: str | None = None
    days: object = None
    event_words: str | None = None
    minutes_before: int | None = None
    include_groups: bool = False
    cooldown_minutes: int | None = None
    reply_mode: str = "text"
    reply_text: str | None = None
    to: str | None = None


def _text(value) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


def _number(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_intent(reply: str) -> Intent:
    first, last = reply.find("{"), reply.rfind("}")
    if first == -1 or last <= first:
        return Intent()
    try:
        data = json.loads(reply[first : last + 1])
    except json.JSONDecodeError:
        return Intent()
    if not isinstance(data, dict) or data.get("action") not in _ACTIONS:
        return Intent()
    return Intent(
        data["action"], _text(data.get("name")), data.get("when") if data.get("when") in ("message", "time", "event") else None,
        _text(data.get("time")), data.get("days"), _text(data.get("event_words")), _number(data.get("minutes_before")),
        data.get("include_groups") is True, _number(data.get("cooldown_minutes")),
        "voice" if data.get("reply_mode") == "voice" else "text", _text(data.get("reply_text")), _text(data.get("to")),
    )


@dataclass(frozen=True)
class _Pending:
    intent: Intent
    candidates: list[Chat]
    expires: float


class AutomationAssistant:
    def __init__(self, llm: ChatClient, service: AutomationService, whatsapp, now: Callable[[], float] = time.time):
        self._llm = llm
        self._service = service
        self._whatsapp = whatsapp  # only to look conversations up by name
        self._now = now
        self._pending: _Pending | None = None

    # ---- a "which one?" question waiting for its answer
    def _live_pending(self) -> _Pending | None:
        if self._pending is not None and self._now() > self._pending.expires:
            self._pending = None
        return self._pending

    def awaiting_choice(self, text: str) -> bool:
        pending = self._live_pending()
        return pending is not None and pick_candidate(text, pending.candidates) is not None

    async def handle(self, text: str) -> str:
        pending = self._live_pending()
        if pending is not None:
            chosen = pick_candidate(text, pending.candidates)
            if chosen is not None:
                self._pending = None
                return await self._create(pending.intent, chosen)
        reply = await self._llm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}])
        intent = parse_intent(reply)
        if intent.action == "list":
            return self._list()
        if intent.action != "create":
            return HELP
        return await self._create(intent, None)

    # ---- listing
    def _list(self) -> str:
        items = self._service._store.list()
        if not items:
            return "Você ainda não tem nenhuma automação."
        lines = [f"- {a.name} ({'ativa' if a.enabled else 'pausada'}): {describe(a.spec)}" for a in items]
        return "Suas automações:\n" + "\n".join(lines)

    # ---- creating
    async def _recipient(self, intent: Intent, chosen: Chat | None) -> tuple[dict | None, str | None]:
        if chosen is not None:
            return {"chat_id": chosen.id, "name": chosen.name}, None
        if not intent.to:
            return None, "Para quem devo enviar a mensagem? Diga o nome da pessoa ou do grupo."
        match, candidates = resolve_chat(intent.to, await self._whatsapp.chats(limit=500))
        if match:
            return {"chat_id": match.id, "name": match.name}, None
        if candidates:
            self._pending = _Pending(intent, candidates, self._now() + PENDING_SECONDS)
            return None, "Qual destes você quer dizer?\n" + "\n".join(f"- {c.label()}" for c in candidates)
        return None, f"Não encontrei nenhuma conversa chamada \"{intent.to}\"."

    async def _create(self, intent: Intent, chosen: Chat | None) -> str:
        if not intent.reply_text:
            return "O que devo responder? Diga o texto exato da mensagem."
        trigger: dict
        to: object = "sender"
        if intent.when == "message":
            trigger = {"type": "whatsapp_message", "include_groups": intent.include_groups}
            if intent.cooldown_minutes is not None:
                trigger["cooldown_minutes"] = intent.cooldown_minutes
        elif intent.when == "time":
            cron = cron_for(intent.time, intent.days)
            if cron is None:
                return "Que horas devo enviar? Diga o horário, por exemplo \"às 9 horas\", e se é todo dia, de segunda a sexta ou no fim de semana."
            trigger = {"type": "schedule", "cron": cron}
        elif intent.when == "event":
            if not intent.event_words:
                return "De que compromisso da agenda se trata? Diga uma palavra do título, por exemplo \"reunião\"."
            trigger = {"type": "calendar_event", "title_contains": intent.event_words, "minutes_before": intent.minutes_before or 0}
        else:
            return HELP
        if intent.when != "message":
            to, problem = await self._recipient(intent, chosen)
            if to is None:
                return problem or HELP
        data = {"name": intent.name, "trigger": trigger,
                "action": {"type": "whatsapp_voice" if intent.reply_mode == "voice" else "whatsapp_text", "to": to, "text": intent.reply_text}}
        try:
            spec = parse_spec(data)
            if spec.action["type"] == "whatsapp_voice":
                await self._service.ensure_audio_possible()
            action = self._service.propose_create(spec)
        except SpecError as exc:
            return f"Não consegui montar a automação: {exc}."
        except AutomationError as exc:
            return str(exc)
        return self._proposal_text(action)

    @staticmethod
    def _proposal_text(action: Action) -> str:
        text = f"{action.summary}\n"
        if action.payload.get("voice"):
            text += "Gravei a resposta em áudio: você pode ouvir antes de confirmar. "
        return f"{text}Confirma? Diga sim ou não.\n[[action:{action.id}]]"
