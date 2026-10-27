"""Live events from OpenWA (Server-Sent Events at /api/events), turned into notices.

The polling watcher notices a dead connection only on its next poll; this listener hears about it at once, and also
about the login steps (QR requested, QR generated, login timed out) that polling cannot see. The latest QR string is
kept in `qr` so the app can show it. Contract, taken from the running server and its dashboard:
  GET /api/events?topics=*&api_key=<key>   text/event-stream; each message is `event: <name>` + `data: {"event", "payload", "ts"}`
It replays recent history on connect, so events older than a few seconds are ignored.
"""

import asyncio
import json
import logging
import time
from collections.abc import Callable, Iterable, Iterator

import httpx

from chakmati.notices import NoticeBoard

log = logging.getLogger(__name__)

_DOWN_STATES = {"DISCONNECTED", "STOPPED", "UNPAIRED", "CONFLICT", "UNLAUNCHED"}
_UP_STATES = {"READY", "CONNECTED"}
_HISTORY_SECONDS = 10.0


def parse_sse_lines(lines: Iterable[str]) -> Iterator[tuple[str, dict]]:
    """(event name, parsed data) for each complete message; messages without a name or with bad JSON are skipped."""
    name = ""
    data: list[str] = []
    for raw in list(lines) + [""]:
        line = raw.rstrip("\r")
        if line == "":
            if name and data:
                try:
                    parsed = json.loads("\n".join(data))
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict):
                    yield name, parsed
            name, data = "", []
        elif line.startswith(":"):
            continue
        elif line.startswith("event:"):
            name = line[6:].strip()
        elif line.startswith("data:"):
            data.append(line[5:].removeprefix(" "))


class WhatsAppEvents:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        board: NoticeBoard,
        now: Callable[[], float] = time.time,
        retry_seconds: float = 3.0,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ):
        self._url = base_url.rstrip("/") + "/api/events"
        self._key = api_key
        self._board = board
        self._now = now
        self._retry = retry_seconds
        self._client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=httpx.Timeout(10.0, read=None)))
        self._state: str | None = None  # "up" | "down"
        self._qr_announced = False
        self.qr: str | None = None

    # ---------------------------------------------------------------- handling
    def _say(self, text: str, key: str) -> None:
        self._board.add("system", text, text, key)

    def handle(self, message: dict) -> None:
        ts = message.get("ts")
        if isinstance(ts, int | float) and ts / 1000 < self._now() - _HISTORY_SECONDS:
            return  # replayed history, not news
        event = message.get("event")
        payload = message.get("payload")
        if event == "session.state.changed" and isinstance(payload, dict):
            state = str(payload.get("nextState") or payload.get("state") or payload.get("currentState") or "").upper()
            if state in _DOWN_STATES and self._state != "down":
                self._state = "down"
                self._say("O WhatsApp foi desconectado.", "wa-down")
            elif state in _UP_STATES and self._state != "up":
                self._state = "up"
                self._qr_announced = False
                self.qr = None
                self._say("O WhatsApp está conectado.", "wa-up")
        elif event == "client.ready" and self._state != "up":
            self._state = "up"
            self.qr = None
            self._say("O WhatsApp está conectado.", "wa-up")
        elif event == "launch.auth.qr.requested":
            if not self._qr_announced:
                self._qr_announced = True
                self._say("O WhatsApp pede para escanear o QR no OpenWA.", "wa-qr")
        elif event == "launch.auth.qr.generated":
            qr = payload if isinstance(payload, str) else (payload or {}).get("qr") if isinstance(payload, dict) else None
            if isinstance(qr, str) and qr:
                self.qr = qr
        elif event == "launch.auth.qr.scanned":
            self.qr = None
        elif event == "launch.auth.timeout":
            self._say("O OpenWA parou de esperar o login. Conecte de novo pelo Ajustes.", "wa-timeout")

    # ---------------------------------------------------------------- connection
    async def run(self) -> None:
        """Listen forever; reconnect after any failure. Cancel the task to stop."""
        while True:
            try:
                async with self._client_factory() as client:
                    async with client.stream(
                        "GET", self._url, params={"topics": "*", "api_key": self._key},
                        headers={"Accept": "text/event-stream"},
                    ) as response:
                        if response.status_code != 200:
                            raise httpx.HTTPError(f"events endpoint answered {response.status_code}")
                        block: list[str] = []
                        async for line in response.aiter_lines():
                            if line.strip() == "":
                                for _, data in parse_sse_lines(block):
                                    self.handle(data)
                                block = []
                            else:
                                block.append(line)
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # OpenWA not running or restarting: try again later
                log.debug("OpenWA events: %s", exc)
            await asyncio.sleep(self._retry)
