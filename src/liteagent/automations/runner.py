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

from ..whatsapp.models import Chat
from .cron import cron_matches
from .store import Automation, AutomationStore

log = logging.getLogger(__name__)
_CONVERSATION = re.compile(r"^[0-9A-Za-z._-]+@(?:c\.us|lid|g\.us)$")


def _plain(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


class AutomationRunner:
    def __init__(self, store: AutomationStore, whatsapp, calendar=None, voice_dir: str | Path = ".",
                 now: Callable[[], float] = time.time):
        self._store = store
        self._whatsapp = whatsapp
        self._calendar = calendar
        self._voice_dir = Path(voice_dir)
        self._now = now

    def recording_path(self, auto_id: str) -> Path:
        return self._voice_dir / f"{auto_id}.ogg"

    async def _perform(self, auto: Automation, chat_id: str, chat_name: str, key: str) -> None:
        action = auto.spec.action
        source = f"automation:{auto.id}"
        try:
            if action["type"] == "whatsapp_voice":
                path = self.recording_path(auto.id)
                if not path.is_file():
                    raise FileNotFoundError("a gravação desta automação não foi encontrada")
                await self._whatsapp.send_automated(chat_id, chat_name, audio=path.read_bytes(), mime="audio/ogg", source=source)
            else:
                await self._whatsapp.send_automated(chat_id, chat_name, text=action["text"], source=source)
        except Exception as exc:  # one broken automation must never stop the others
            log.warning("automation %s failed: %s", auto.name, exc)
            self._store.record_run(auto.id, key, f"falhou: {exc}", self._now())
            return
        self._store.record_run(auto.id, key, "ok", self._now())

    # ---- a message arrived
    async def on_whatsapp_messages(self, fresh: Sequence[tuple[Chat, int]]) -> None:
        for auto in self._store.list(enabled_only=True):
            trigger = auto.spec.trigger
            if trigger["type"] != "whatsapp_message":
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
    async def tick(self, when: datetime) -> None:
        for auto in self._store.list(enabled_only=True):
            trigger, action = auto.spec.trigger, auto.spec.action
            if trigger["type"] == "schedule":
                key = when.strftime("%Y%m%d%H%M")
                if cron_matches(trigger["cron"], when) and self._store.last_run(auto.id, key) is None:
                    await self._perform(auto, action["to"]["chat_id"], action["to"]["name"], key)
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
                await self._perform(auto, action["to"]["chat_id"], action["to"]["name"], key)
