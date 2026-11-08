"""Runs the automations: when a message arrives, when a schedule's minute comes, when a calendar event is about to start.

What it sends is exactly what the person approved when creating the automation. Nothing in a received message ever reaches
the reply. Safety nets: groups and non-conversation ids are skipped by default; one automatic reply per person per
cooldown (and a failed attempt does not use the cooldown up); and every send goes through the WhatsApp service's hourly limit.
"""

import logging
import re
import time
import unicodedata
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from pathlib import Path

from chakmati.features.whatsapp.models import Chat
from chakmati.features.automations.cron import cron_matches
from chakmati.features.automations.models import in_hours
from chakmati.features.automations.store import Automation, AutomationStore

log = logging.getLogger(__name__)
CATCHUP_MINUTES = 30   # a scheduled minute missed for up to this long (the computer slept, the app was closed) still runs, and the notice says it was late
LATE_AFTER = 120.0     # seconds: the ticker looks at the clock every 20 s, so a run a minute after its time is on time; later than this is "atrasada"
PREFIX = "Resposta automática Chakmati: "  # every automatic text says what it is, so nobody mistakes it for the person
LABEL = PREFIX.rstrip()  # the line that goes before a voice note: just the label, no word about what follows ("Resposta automática Chakmati:")
_CONVERSATION = re.compile(r"^[0-9A-Za-z._-]+@(?:c\.us|lid|g\.us)$")


def _how_long(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes} min"
    hours, rest = divmod(minutes, 60)
    return f"{hours} h" + (f" {rest} min" if rest else "")


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


class AutomationRunner:
    def __init__(self, store: AutomationStore, whatsapp, calendar=None, voice_dir: str | Path = ".",
                 now: Callable[[], float] = time.time, home=None, notices=None):
        self._store = store
        self._notices = notices   # the notice board: every run, failure and late run becomes a notice in "Avisos recentes"
        self._whatsapp = whatsapp
        self._home = home   # the house (HomeService): what an automation of devices and music runs through
        self._calendar = calendar
        self._voice_dir = Path(voice_dir)
        self._now = now

    def recording_path(self, auto_id: str) -> Path:
        return self._voice_dir / f"{auto_id}.ogg"

    def _record(self, auto: Automation, key: str, outcome: str, who: str = "", late: float = 0.0, due: datetime | None = None) -> None:
        """Writes the run to the log and tells the person: it ran, it ran late, it ran only in part, or it failed."""
        self._store.record_run(auto.id, key, outcome, self._now())
        if self._notices is None:
            return
        name = auto.name
        late_text = ""
        if late >= LATE_AFTER and due is not None:
            late_text = f" com atraso de {_how_long(late)} (era para as {due:%H:%M})"
        to = f" para {who}" if who else ""
        if outcome == "ok":
            text, masked = f"A automação “{name}” rodou{late_text}{to}.", ("Uma automação rodou com atraso." if late_text else "Uma automação rodou.")
        elif outcome.startswith("parcial"):
            text, masked = f"A automação “{name}” rodou só em parte{late_text}: {outcome.partition(':')[2].strip()}", "Uma automação rodou só em parte."
        else:
            reason = outcome.partition(":")[2].strip() or "erro desconhecido"
            text, masked = f"A automação “{name}” falhou{late_text}: {reason}", "Uma automação falhou."
        self._notices.add("automation", text, masked, f"automation:{auto.id}:{key}")

    async def _perform(self, auto: Automation, chat_id: str, chat_name: str, key: str, late: float = 0.0, due: datetime | None = None) -> None:
        action = auto.spec.action
        source = f"automation:{auto.id}"
        try:
            if action["type"] == "whatsapp_voice":
                path = self.recording_path(auto.id)
                if not path.is_file():
                    raise FileNotFoundError("a gravação desta automação não foi encontrada")
                audio = path.read_bytes()
                check = getattr(self._whatsapp, "media_supported", None)
                if check is not None and await check() is not True:  # no label if the voice note cannot follow it
                    raise RuntimeError("o envio de áudio não está disponível agora")
                # the label first, so the voice note is never mistaken for the person themself
                await self._whatsapp.send_automated(chat_id, chat_name, text=LABEL, source=source)
                try:
                    await self._whatsapp.send_automated(chat_id, chat_name, audio=audio, mime="audio/ogg", source=source)
                except Exception as exc:  # the label already went out: count this as a reply, or every new message would repeat the label
                    log.warning("automation %s sent the label but not the audio: %s", auto.name, exc)
                    self._record(auto, key, f"parcial: só a mensagem de texto foi enviada ({exc})", chat_name, late, due)
                    return
            else:
                await self._whatsapp.send_automated(chat_id, chat_name, text=PREFIX + action["text"], source=source)
        except Exception as exc:  # one broken automation must never stop the others
            log.warning("automation %s failed: %s", auto.name, exc)
            self._record(auto, key, f"falhou: {exc}", chat_name, late, due)
            return
        self._record(auto, key, "ok", chat_name, late, due)

    async def _perform_home(self, auto: Automation, key: str, late: float = 0.0, due: datetime | None = None) -> None:
        """The steps of a house automation, one after the other; a failing step is said and the next ones still run (the light must not depend on the music)."""
        failures = []
        if self._home is None:
            failures.append("a casa não está ligada")
        else:
            for step in auto.spec.action["steps"]:
                try:
                    await self._home.run_step(step)
                except Exception as exc:   # one broken step must never stop the others, nor the other automations
                    log.warning("automation %s: a step failed: %s", auto.name, exc)
                    failures.append(f"{step['entity']['name']}: {exc}")
        self._record(auto, key, "ok" if not failures else "falhou: " + "; ".join(failures)[:300], "", late, due)

    # ---- a message arrived
    async def on_whatsapp_messages(self, fresh: Sequence[tuple[Chat, int]]) -> None:
        for auto in self._store.list(enabled_only=True):
            trigger = auto.spec.trigger
            if trigger["type"] != "whatsapp_message":
                continue
            if not in_hours(trigger.get("hours"), datetime.fromtimestamp(self._now())):   # outside its hours it does nothing (and uses no cooldown)
                continue
            for chat, _delta in fresh:
                if not _CONVERSATION.match(chat.id) or (chat.is_group and not trigger["include_groups"]):
                    continue
                last = self._store.last_run(auto.id, chat.id)
                if last is not None and self._now() - last < trigger["cooldown_minutes"] * 60:
                    continue
                to = auto.spec.action["to"]
                if to == "sender":
                    await self._perform(auto, chat.id, chat.name, chat.id)
                else:
                    await self._perform(auto, to["chat_id"], to["name"], chat.id)

    # ---- time passed (called every few seconds)
    def _due_minute(self, auto: Automation, when: datetime) -> datetime | None:
        """The latest minute this schedule was due, up to CATCHUP_MINUTES ago, that has not run yet (and not before the automation existed)."""
        cron = auto.spec.trigger["cron"]
        now_minute = when.replace(second=0, microsecond=0)
        for back in range(CATCHUP_MINUTES + 1):
            minute = now_minute - timedelta(minutes=back)
            if minute.timestamp() < auto.created_at - 60:
                return None
            if cron_matches(cron, minute) and self._store.last_run(auto.id, minute.strftime("%Y%m%d%H%M")) is None:
                return minute
        return None

    async def tick(self, when: datetime) -> None:
        for auto in self._store.list(enabled_only=True):
            trigger, action = auto.spec.trigger, auto.spec.action
            if trigger["type"] == "schedule":
                due = self._due_minute(auto, when)
                if due is not None:
                    key, late = due.strftime("%Y%m%d%H%M"), (when - due).total_seconds()
                    if action["type"] == "home_steps":
                        await self._perform_home(auto, key, late, due)
                    else:
                        await self._perform(auto, action["to"]["chat_id"], action["to"]["name"], key, late, due)
            elif trigger["type"] == "calendar_event" and self._calendar is not None:
                await self._calendar_trigger(auto, when)

    async def _calendar_trigger(self, auto: Automation, when: datetime) -> None:
        trigger, action = auto.spec.trigger, auto.spec.action
        before = trigger["minutes_before"]
        try:
            events = self._calendar.events(when, when + timedelta(minutes=before + 2))
        except Exception as exc:
            log.warning("automation %s could not read the calendar: %s", auto.name, exc)
            return
        wanted = _plain(trigger["title_contains"])
        for event in events:
            starts_in = (event.start - when).total_seconds()
            if event.all_day or wanted not in _plain(event.title) or not -60 <= starts_in <= before * 60 + 30:
                continue
            key = f"{event.id}@{event.start.isoformat()}"
            if self._store.last_run(auto.id, key) is None:
                if action["type"] == "home_steps":
                    await self._perform_home(auto, key)
                else:
                    await self._perform(auto, action["to"]["chat_id"], action["to"]["name"], key)
