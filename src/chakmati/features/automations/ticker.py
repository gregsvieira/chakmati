"""Lets time-based automations look at the clock every few seconds."""

from datetime import datetime


class AutomationTicker:
    """Lets time-based automations (schedule, calendar event) look at the clock every few seconds."""

    def __init__(self, runner, interval: float = 20.0, clock=lambda: datetime.now().astimezone()):
        self._runner = runner
        self.interval = interval
        self._clock = clock

    async def poll_once(self) -> None:
        await self._runner.tick(self._clock())
