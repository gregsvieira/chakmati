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
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

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
    def __init__(self, watchers: Sequence[Watcher], background: Sequence[Callable[[], Awaitable[None]]] = ()):
        self._watchers = list(watchers)
        self._background = list(background)  # long-running listeners (e.g. an event stream), restarted by themselves
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
        self._tasks += [asyncio.create_task(run()) for run in self._background]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks = []
