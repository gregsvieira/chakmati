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
from dataclasses import dataclass, replace

from chakmati.shared.approvals import Action
from chakmati.shared.llm import ChatClient
from chakmati.features.whatsapp.assistant import pick_candidate, resolve_chat
from chakmati.features.whatsapp.models import Chat
from chakmati.features.automations.models import HOME_ACTIONS, MAX_STEPS, SpecError, describe, parse_spec
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
  "hours_from", "hours_to": for "message", the hours the automation works as "HH:MM" in 24 hours when the user said them ("between 10pm and 7:50am" -> "22:00" and "07:50"); otherwise null
  "home_steps": for "time" and "event", when the user wants things done in the house (lights, curtains, plugs, a blind, the thermostat): a list of {"action": "on" (turn on / open a light, plug), "off", "open" (a curtain, blind), "close", "lock", "scene" (activate a scene), "brightness" (value = percent) or "set_temperature" (value = degrees), "target": the device name as the user said it ("luz do quarto"), "value": a number or null}; otherwise []
  "music": for "time" and "event", when the user wants a song, artist or playlist played on an Alexa / Echo speaker: {"query": what to play exactly as said ("Raul Seixas"), "device": the speaker's name if the user said one, otherwise null}; otherwise null
  "cooldown_minutes": only if the user said how often to reply to the same person, otherwise null
  "reply_mode": "voice" if the user wants an audio / recorded / voice reply, otherwise "text"
  "reply_text": the reply EXACTLY as the user wants it written (do not add, remove or reword anything), or null
  "to": for "time" and "event", the name of the person or group that receives the message; null for "message" (the reply goes to whoever wrote)
Never invent anything the user did not say."""

HELP = ("Não entendi o pedido de automação. Exemplos: \"sempre que alguém me escrever no WhatsApp, responda: estou ocupado\", "
        "\"todo dia às 7h ligue a luz do quarto e abra a cortina\", \"de segunda a sexta às 6h30 toque Raul Seixas na Alexa\", "
        "\"todo dia útil às 9h mande bom dia para o João\", \"5 minutos antes de toda reunião avise a Maria\".")
PENDING_SECONDS = 300.0
_TIME = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")
_DAYS = {"daily": "*", "weekdays": "1-5", "weekend": "0,6"}
_ACTIONS = {"create", "list"}
_T = r"(\d{1,2})(?:\s*[:h]\s*(\d{2})?|\s*horas?)"    # 22:00, 22h, 7h50, 7 horas: the hour always carries a ":", an "h" or "horas", so "de 5 a 10" is not a time
_RANGE = re.compile(rf"(?:\bentre\s+(?:as\s+)?|\bd[ae]s?\s+(?:as\s+)?|\bde\s+){_T}\s*(?:e|a|[àa]s|at[ée])\s+(?:as\s+|às\s+)?{_T}", re.IGNORECASE)


_AT = re.compile(r"\b(?:[àa]s|[àa]\s+partir\s+das)\s+(\d{1,2})(?:\s*[:h]\s*(\d{2})?|\s*horas?)", re.IGNORECASE)
_WEEKDAYS = re.compile(r"\bde\s+segunda\s+(?:a|à|até)\s+sexta\b|\bdias?\s+[úu]t(?:eis|il)\b|\bsegunda\s+a\s+sexta\b", re.IGNORECASE)
_WEEKEND = re.compile(r"\b(?:fim|fins)\s+de\s+semana\b|\bs[áa]bados?\s+e\s+domingos?\b", re.IGNORECASE)
_DAILY = re.compile(r"\btodo\s+dia\b|\btodos\s+os\s+dias\b|\ball\s+days\b", re.IGNORECASE)


def time_from_text(text: str) -> str | None:
    """The time of day the person said ("às 6h30", "às 7h", "às 07:00") as "HH:MM", or None. Read in code too: a small model sometimes leaves it out of its JSON, and
    asking "que horas?" about a request that said the time is the kind of thing that makes an assistant tiresome."""
    match = _AT.search(text or "")
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2) or 0)
    return f"{hour:02d}:{minute:02d}" if hour <= 23 and minute <= 59 else None


def days_from_text(text: str) -> str | None:
    """"weekdays" / "weekend" / "daily" when the person said so, else None. "de segunda a sexta" must not become every day because the model dropped it."""
    text = text or ""
    if _WEEKDAYS.search(text):
        return "weekdays"
    if _WEEKEND.search(text):
        return "weekend"
    return "daily" if _DAILY.search(text) else None


def hours_from_text(text: str) -> dict | None:
    """The hours the person said ("entre as 22:00 e as 07:50", "das 22h às 7h", "de 18:00 até 08:30") as {"from": "22:00", "to": "07:50"}, or None when they did not say
    any. Read here, in code, from the person's own words: the model may miss them, and an automation that was meant to work at night must not end up working all day.
    ValueError when they gave hours that do not exist ("das 25h às 7h"), so it is said instead of ignored."""
    text = text or ""
    # only the request itself, never the reply: "responda: estou ocupado das 9h às 17h" is a message to send, not the hours the automation works
    reply = re.search(r"\b(?:respond\w*|mand\w*|envi\w*|diga|dizer|escrev\w*)\b.*?:\s", text, re.IGNORECASE | re.DOTALL)   # a ": " (colon and space), not the colon of 22:00
    match = _RANGE.search(text[: reply.end()] if reply else text)
    if not match:
        return None
    h1, m1, h2, m2 = match.groups()
    values = [(int(h1), int(m1 or 0)), (int(h2), int(m2 or 0))]
    if any(h > 23 or m > 59 for h, m in values):
        raise ValueError("esse horário não existe")
    out = {"from": f"{values[0][0]:02d}:{values[0][1]:02d}", "to": f"{values[1][0]:02d}:{values[1][1]:02d}"}
    if out["from"] == out["to"]:
        raise ValueError("o horário precisa começar e terminar em momentos diferentes")
    return out


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
    hours: dict | None = None   # {"from": "22:00", "to": "07:50"}: set by the code from the person's words (or from the model's, when they are valid)
    steps: tuple = ()           # what to do in the house: ({"action": "on", "target": "luz do quarto", "value": None}, ...)
    music: dict | None = None   # {"query": "Raul Seixas", "device": "sala" or None}


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
        _model_hours(data.get("hours_from"), data.get("hours_to")),
        _model_steps(data.get("home_steps")), _model_music(data.get("music")),
    )


def _model_steps(raw) -> tuple:
    out = []
    for item in raw if isinstance(raw, list) else []:
        if isinstance(item, dict) and item.get("action") in HOME_ACTIONS and _text(item.get("target")):
            value = item.get("value")
            out.append({"action": item["action"], "target": _text(item["target"]), "value": value if isinstance(value, (int, float)) and not isinstance(value, bool) else None})
    return tuple(out[:MAX_STEPS])


def _model_music(raw) -> dict | None:
    return {"query": _text(raw.get("query")), "device": _text(raw.get("device"))} if isinstance(raw, dict) and _text(raw.get("query")) else None


def _model_hours(start, end) -> dict | None:
    ok = all(isinstance(x, str) and re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", x) for x in (start, end))
    return {"from": start, "to": end} if ok and start != end else None


@dataclass(frozen=True)
class _Pending:
    intent: Intent
    candidates: list[Chat]
    expires: float


class AutomationAssistant:
    def __init__(self, llm: ChatClient, service: AutomationService, whatsapp, now: Callable[[], float] = time.time, home=None):
        self._llm = llm
        self._service = service
        self._whatsapp = whatsapp  # only to look conversations up by name
        self._home = home  # the house (HomeService): only to find the devices by name; the person's words never reach it as a command
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
        try:
            said = hours_from_text(text)
        except ValueError as exc:
            return f"Não entendi o horário: {exc}. Diga, por exemplo, \"entre as 22:00 e as 07:50\"."
        if said is not None:
            intent = replace(intent, hours=said)   # the person's own words win over the model's reading
        if intent.when == "time" and intent.action == "create":
            # a time and the days the person said are read in code too; theirs win over a model that dropped or changed them
            intent = replace(intent, time=time_from_text(text) or intent.time, days=days_from_text(text) or intent.days)
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
        if self._whatsapp is None:
            return None, "O WhatsApp não está ligado: não dá para enviar mensagens por automação."
        if not intent.to:
            return None, "Para quem devo enviar a mensagem? Diga o nome da pessoa ou do grupo."
        match, candidates = resolve_chat(intent.to, await self._whatsapp.chats(limit=500))
        if match:
            return {"chat_id": match.id, "name": match.name}, None
        if candidates:
            self._pending = _Pending(intent, candidates, self._now() + PENDING_SECONDS)
            return None, "Qual destes você quer dizer?\n" + "\n".join(f"- {c.label()}" for c in candidates)
        return None, f"Não encontrei nenhuma conversa chamada \"{intent.to}\"."

    # ---- the house: devices and music at a time
    async def _home_steps(self, intent: Intent) -> tuple[list[dict] | None, str | None]:
        """The steps with the devices found BY NAME in code (never by the model): (steps, None), or (None, the question or problem for the person)."""
        if self._home is None:
            return None, "A casa inteligente não está ligada. Conecte o Home Assistant em Ajustes > Assistente de Casa e Alexa."
        entities = await self._home.entities()
        steps: list[dict] = []
        for want in intent.steps:
            entity, candidates = self._home.find([e for e in entities if e.domain != "media_player"], want["target"])
            if entity is None:
                if candidates:
                    return None, f"Qual destes é \"{want['target']}\"?\n" + "\n".join(f"- {c.name}" for c in candidates) + "\nPeça de novo com o nome completo."
                return None, f"Não encontrei nenhum dispositivo chamado \"{want['target']}\" na casa."
            step = {"kind": "device", "action": want["action"], "entity": {"id": entity.id, "name": entity.name, "device_class": entity.device_class}}
            if want["value"] is not None:
                step["value"] = want["value"]
            steps.append(step)
        if intent.music:
            players = [e for e in entities if e.domain == "media_player"]
            speaker, candidates = self._home.find(players, intent.music["device"]) if intent.music["device"] else (None, [])
            if speaker is None and not candidates:
                # no speaker named, or the model said "Alexa" / "echo" (which is no name): the one that plays, or the only one there is
                speaker, candidates = self._home.default_player(entities)
            if speaker is None:
                if candidates:
                    return None, "Em qual aparelho de música?\n" + "\n".join(f"- {c.name}" for c in candidates) + "\nPeça de novo dizendo o aparelho."
                return None, "Não encontrei nenhum aparelho de música (Alexa) no Home Assistant."
            steps.append({"kind": "music", "entity": {"id": speaker.id, "name": speaker.name}, "query": intent.music["query"]})
        return steps, None

    async def _create_home(self, intent: Intent) -> str:
        if intent.when not in ("time", "event"):
            return "Uma automação da casa precisa de um horário (\"todo dia às 7h\") ou de um compromisso da agenda. Ela não pode começar por uma mensagem recebida."
        if intent.when == "time":
            cron = cron_for(intent.time, intent.days)
            if cron is None:
                return "Que horas devo fazer isso? Diga o horário, por exemplo \"às 7 horas\", e se é todo dia, de segunda a sexta ou no fim de semana."
            trigger: dict = {"type": "schedule", "cron": cron}
        else:
            if not intent.event_words:
                return "De que compromisso da agenda se trata? Diga uma palavra do título, por exemplo \"reunião\"."
            trigger = {"type": "calendar_event", "title_contains": intent.event_words, "minutes_before": intent.minutes_before or 0}
        steps, problem = await self._home_steps(intent)
        if steps is None:
            return problem or HELP
        try:
            spec = parse_spec({"name": intent.name, "trigger": trigger, "action": {"type": "home_steps", "steps": steps}})
            action = self._service.propose_create(spec)
        except SpecError as exc:
            return f"Não consegui montar a automação: {exc}."
        except AutomationError as exc:
            return str(exc)
        return self._proposal_text(action)

    async def _create(self, intent: Intent, chosen: Chat | None) -> str:
        if (intent.steps or intent.music) and not intent.reply_text:
            return await self._create_home(intent)
        if not intent.reply_text:
            return "O que devo responder? Diga o texto exato da mensagem."
        trigger: dict
        to: object = "sender"
        if intent.when == "message":
            trigger = {"type": "whatsapp_message", "include_groups": intent.include_groups}
            if intent.cooldown_minutes is not None:
                trigger["cooldown_minutes"] = intent.cooldown_minutes
            if intent.hours:
                trigger["hours"] = intent.hours
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
