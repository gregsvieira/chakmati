"""Proactive notices: things the assistant tells the user without being asked.

Watchers poll the integrations (WhatsApp, calendar, pending approvals) and post short notices to a board; the desktop
app reads the board (HTTP or Server-Sent Events). Every notice carries two texts: the full one ("Você recebeu uma nova
mensagem de Maria") and a masked one with no names or titles, so the UI can switch to a discreet mode without asking
the engine anything.
"""

import asyncio
import logging
import math
import time
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from .whatsapp.openwa import WhatsAppError

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Notice:
    id: int
    kind: str  # "whatsapp" | "calendar" | "approval" | "system"
    text: str
    masked: str
    ts: float
    key: str = ""


class NoticeBoard:
    def __init__(self, max_items: int = 200, now: Callable[[], float] = time.time):
        self._items: deque[Notice] = deque(maxlen=max_items)
        self._now = now
        self._next = 1
        self._waiters: list[asyncio.Future[None]] = []

    @property
    def last_id(self) -> int:
        return self._next - 1

    def add(self, kind: str, text: str, masked: str, key: str = "") -> Notice:
        notice = Notice(self._next, kind, text, masked, self._now(), key)
        self._next += 1
        self._items.append(notice)
        for waiter in self._waiters:
            if not waiter.done():
                waiter.set_result(None)
        self._waiters.clear()
        return notice

    def since(self, after_id: int) -> list[Notice]:
        return [n for n in self._items if n.id > after_id]

    async def wait_for(self, after_id: int, timeout: float) -> list[Notice]:
        """Notices newer than `after_id`; waits up to `timeout` seconds if there are none yet."""
        backlog = self.since(after_id)
        if backlog:
            return backlog
        waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._waiters.append(waiter)
        try:
            await asyncio.wait_for(waiter, timeout)
        except asyncio.TimeoutError:
            if waiter in self._waiters:
                self._waiters.remove(waiter)
            return []
        return self.since(after_id)


class Watcher(Protocol):
    interval: float

    async def poll_once(self) -> None: ...


# ----------------------------------------------------------------------------- WhatsApp
class WhatsAppWatcher:
    """Announces new unread messages. The first poll is only a baseline (plus one summary), so starting the app
    does not replay every old unread chat. Muted and archived chats stay silent, as they do on the phone."""

    def __init__(self, service, board: NoticeBoard, interval: float = 10.0):
        self._service = service
        self._board = board
        self.interval = interval
        self._seen: dict[str, int] | None = None
        self._down = False

    async def poll_once(self) -> None:
        try:
            chats = await self._service.chats(limit=500)
        except WhatsAppError:
            if not self._down:
                self._down = True
                self._board.add("system", "O WhatsApp está desconectado. Abra o OpenWA e escaneie o QR.",
                                "O WhatsApp está desconectado.")
            return
        if self._down:
            self._down = False
            self._board.add("system", "O WhatsApp voltou a funcionar.", "O WhatsApp voltou a funcionar.")

        if self._seen is None:  # baseline
            self._seen = {c.id: c.unread for c in chats}
            count = sum(1 for c in chats if c.unread > 0 and not c.muted and not c.archived)
            if count:
                what = "1 conversa" if count == 1 else f"{count} conversas"
                self._board.add("whatsapp", f"Você tem {what} com mensagens não lidas",
                                "Você tem mensagens não lidas no WhatsApp", "summary")
            return

        fresh = []
        for c in chats:
            delta = c.unread - self._seen.get(c.id, 0)
            self._seen[c.id] = c.unread
            if delta > 0 and not c.muted and not c.archived:
                fresh.append((c, delta))
        if not fresh:
            return
        if len(fresh) > 3:
            names = ", ".join(c.name for c, _ in fresh[:3])
            total = sum(d for _, d in fresh)
            self._board.add("whatsapp", f"Você recebeu novas mensagens de {names} e mais {len(fresh) - 3}",
                            f"Você recebeu {total} novas mensagens no WhatsApp", "many")
            return
        for c, delta in fresh:
            if c.is_group:
                text = f"Nova mensagem no grupo {c.name}" if delta == 1 else f"{delta} novas mensagens no grupo {c.name}"
            else:
                text = (f"Você recebeu uma nova mensagem de {c.name}" if delta == 1
                        else f"Você recebeu {delta} novas mensagens de {c.name}")
            masked = ("Você recebeu uma nova mensagem no WhatsApp" if delta == 1
                      else f"Você recebeu {delta} novas mensagens no WhatsApp")
            self._board.add("whatsapp", text, masked, c.id)


# ----------------------------------------------------------------------------- calendar
class CalendarWatcher:
    def __init__(self, service, board: NoticeBoard, interval: float = 60.0, lead_minutes: int = 10,
                 now: Callable[[], datetime] = lambda: datetime.now().astimezone()):
        self._service = service
        self._board = board
        self.interval = interval
        self._lead = timedelta(minutes=lead_minutes)
        self._now = now
        self._announced: set[str] = set()

    async def poll_once(self) -> None:
        now = self._now()
        events = await asyncio.to_thread(self._service.events, now - timedelta(minutes=1), now + self._lead)
        for e in events:
            key = f"{e.id}@{e.start.isoformat()}"
            starts_in = (e.start - now).total_seconds()
            if e.all_day or key in self._announced or starts_in < -60 or starts_in > self._lead.total_seconds():
                continue
            self._announced.add(key)
            text = f"Agora: {e.title}" if starts_in <= 60 else f"Em {math.ceil(starts_in / 60)} min: {e.title}"
            self._board.add("calendar", text, "Você tem um compromisso em breve", key)
        if len(self._announced) > 500:
            self._announced.clear()


# ----------------------------------------------------------------------------- approvals
class ApprovalWatcher:
    def __init__(self, services: Sequence, board: NoticeBoard, interval: float = 3.0):
        self._services = list(services)
        self._board = board
        self.interval = interval
        self._known: set[str] = set()

    async def poll_once(self) -> None:
        items = []
        for service in self._services:
            items.extend(await asyncio.to_thread(service.pending))
        new = [a for a in items if a.id not in self._known]
        self._known.update(a.id for a in items)
        if not new:
            return
        if len(new) == 1:
            first_line = new[0].summary.splitlines()[0] if new[0].summary else ""
            self._board.add("approval", f"Há uma ação aguardando a sua aprovação: {first_line}",
                            "Há uma ação aguardando a sua aprovação", new[0].id)
        else:
            text = f"Há {len(new)} ações aguardando a sua aprovação"
            self._board.add("approval", text, text, "many")


# ----------------------------------------------------------------------------- runner
class Notifier:
    def __init__(self, watchers: Sequence[Watcher]):
        self._watchers = list(watchers)
        self._tasks: list[asyncio.Task] = []

    @staticmethod
    async def _loop(watcher: Watcher) -> None:
        while True:
            try:
                await watcher.poll_once()
            except Exception:  # a broken watcher must never take the others (or the app) down
                log.warning("watcher %s failed", type(watcher).__name__, exc_info=True)
            await asyncio.sleep(watcher.interval)

    def start(self) -> None:
        self._tasks = [asyncio.create_task(self._loop(w)) for w in self._watchers]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
