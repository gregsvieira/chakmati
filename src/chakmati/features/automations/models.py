"""What an automation is: a trigger (when) and an action (what to do), validated before anything is stored.

Everything the person asked for is checked here: the reply text is theirs, word for word, and can never come from a received
message. Defaults are cautious: groups are skipped, and a person gets at most one automatic reply per cooldown.
"""

import re
from dataclasses import dataclass

from chakmati.features.automations.cron import CronError, describe_cron, fires_per_day, validate_cron

MAX_NAME = 60
MAX_TEXT = 1000
MAX_RUNS_PER_DAY = 24
DEFAULT_COOLDOWN_MINUTES = 120
_HHMM = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_RECIPIENT = re.compile(r"^[0-9A-Za-z._-]+@(?:c\.us|lid|g\.us)$")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
TRIGGERS = ("whatsapp_message", "schedule", "calendar_event")
ACTIONS = ("whatsapp_text", "whatsapp_voice")


class SpecError(ValueError):
    pass


@dataclass(frozen=True)
class Spec:
    name: str
    trigger: dict
    action: dict


def _int(value, low: int, high: int, what: str, default: int | None = None) -> int:
    if value is None and default is not None:
        return default
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise SpecError(f"{what} must be a number from {low} to {high}")
    return value


def _hours(raw) -> dict | None:
    """The hours the automation works, {"from": "22:00", "to": "07:50"} (a window that crosses midnight is fine); None = always."""
    if raw is None:
        return None
    if not isinstance(raw, dict) or not all(isinstance(raw.get(k), str) and _HHMM.match(raw[k]) for k in ("from", "to")):
        raise SpecError("the hours must be {\"from\": \"HH:MM\", \"to\": \"HH:MM\"} in 24 hours")
    if raw["from"] == raw["to"]:
        raise SpecError("the hours must start and end at different times")
    return {"from": raw["from"], "to": raw["to"]}


def _minutes(hhmm: str) -> int:
    return int(hhmm[:2]) * 60 + int(hhmm[3:])


def in_hours(hours: dict | None, when) -> bool:
    """Whether `when` (a datetime) falls inside the hours; always true without hours. The window includes its start and excludes its end, and "22:00" to
    "07:50" means from 22:00 of one day until 07:50 of the next."""
    if not hours:
        return True
    now, start, end = when.hour * 60 + when.minute, _minutes(hours["from"]), _minutes(hours["to"])
    return start <= now < end if start < end else now >= start or now < end


def _trigger(raw) -> dict:
    if not isinstance(raw, dict) or raw.get("type") not in TRIGGERS:
        raise SpecError(f"trigger type must be one of {', '.join(TRIGGERS)}")
    kind = raw["type"]
    if kind == "whatsapp_message":
        groups = raw.get("include_groups", False)
        if not isinstance(groups, bool):
            raise SpecError("include_groups must be true or false")
        out = {"type": kind, "include_groups": groups,
               "cooldown_minutes": _int(raw.get("cooldown_minutes"), 1, 1440, "cooldown_minutes", DEFAULT_COOLDOWN_MINUTES)}
        hours = _hours(raw.get("hours"))
        if hours:
            out["hours"] = hours
        return out
    if kind == "schedule":
        cron = raw.get("cron")
        if not isinstance(cron, str):
            raise SpecError("a schedule needs a cron expression")
        try:
            validate_cron(cron.strip())
        except CronError as exc:
            raise SpecError(str(exc)) from None
        if fires_per_day(cron.strip()) > MAX_RUNS_PER_DAY:
            raise SpecError(f"a schedule may fire at most {MAX_RUNS_PER_DAY} times a day")
        return {"type": kind, "cron": " ".join(cron.split())}
    title = raw.get("title_contains")
    if not isinstance(title, str) or not title.strip() or len(title.strip()) > MAX_NAME:
        raise SpecError("a calendar trigger needs the words the event title must contain (up to 60 characters)")
    return {"type": kind, "title_contains": title.strip(), "minutes_before": _int(raw.get("minutes_before"), 0, 120, "minutes_before", 0)}


def _action(raw, trigger_type: str) -> dict:
    if not isinstance(raw, dict) or raw.get("type") not in ACTIONS:
        raise SpecError(f"action type must be one of {', '.join(ACTIONS)}")
    text = raw.get("text")
    if not isinstance(text, str) or not text.strip() or len(text.strip()) > MAX_TEXT or _CONTROL.search(text):
        raise SpecError(f"the reply must have 1 to {MAX_TEXT} characters and no control characters")
    to = raw.get("to")
    if to == "sender":
        if trigger_type != "whatsapp_message":
            raise SpecError("replying to the sender only makes sense when the trigger is a received message")
        target: object = "sender"
    elif isinstance(to, dict) and isinstance(to.get("chat_id"), str) and _RECIPIENT.match(to["chat_id"]):
        name = to.get("name")
        target = {"chat_id": to["chat_id"], "name": name.strip()[:80] if isinstance(name, str) and name.strip() else to["chat_id"]}
    else:
        raise SpecError("the recipient must be the sender or a conversation with a valid id")
    result = {"type": raw["type"], "to": target, "text": text.strip()}
    if raw.get("own_voice") is True and raw["type"] == "whatsapp_voice":  # the recording is the person's own voice
        result["own_voice"] = True
    return result


def parse_spec(data) -> Spec:
    if not isinstance(data, dict):
        raise SpecError("an automation must be an object")
    trigger = _trigger(data.get("trigger"))
    action = _action(data.get("action"), trigger["type"])
    name = data.get("name")
    if name is not None and not isinstance(name, str):
        raise SpecError("the name must be text")
    name = (name or "").strip()
    if len(name) > MAX_NAME:
        raise SpecError(f"the name must have at most {MAX_NAME} characters")
    return Spec(name or _default_name(trigger), trigger, action)


def _default_name(trigger: dict) -> str:
    return {"whatsapp_message": "Resposta automática", "schedule": "Mensagem agendada", "calendar_event": "Aviso de compromisso"}[trigger["type"]]


def _cooldown_words(minutes: int) -> str:
    if minutes % 60 == 0:
        hours = minutes // 60
        return "1 hora" if hours == 1 else f"{hours} horas"
    return f"{minutes} minutos"


def describe(spec: Spec) -> str:
    """One plain sentence saying what will happen: this is what the person confirms."""
    trigger, action = spec.trigger, spec.action
    mode = ("em áudio, com a sua voz gravada" if action.get("own_voice") else "em áudio, com a minha voz") if action["type"] == "whatsapp_voice" else "por mensagem"
    who = "essa pessoa" if action["to"] == "sender" else action["to"]["name"]
    reply = f"responder {mode} para {who}" if action["to"] == "sender" else f"enviar {mode} para {who}"
    quoted = f"«{action['text']}»" + (" (antes do áudio vai a mensagem \"Resposta automática Chakmati: Áudio\")" if action["type"] == "whatsapp_voice" else ' (a mensagem sai começando com \"Resposta automática Chakmati:\")')
    if trigger["type"] == "whatsapp_message":
        scope = "em conversas individuais e em grupos" if trigger["include_groups"] else "em conversas individuais (grupos ficam de fora)"
        hours = trigger.get("hours")
        when = f" entre as {hours['from']} e as {hours['to']}" if hours else ""
        return (f"Quando alguém te escrever no WhatsApp{when}, {scope}, {reply}: {quoted}. "
                f"No máximo uma resposta por pessoa a cada {_cooldown_words(trigger['cooldown_minutes'])}.")
    if trigger["type"] == "schedule":
        return f"{describe_cron(trigger['cron']).capitalize()}, {reply}: {quoted}."
    before = trigger["minutes_before"]
    when = f"{before} min antes de" if before else "Quando começar"
    return f"{when} compromissos da agenda com «{trigger['title_contains']}» no título, {reply}: {quoted}."
