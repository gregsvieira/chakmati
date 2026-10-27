"""Announces calendar events that are about to start on the notice board."""

import asyncio
import math
from collections.abc import Callable
from datetime import datetime, timedelta

from chakmati.shared.notices import NoticeBoard


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
