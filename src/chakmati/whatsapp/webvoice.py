"""Voice notes through the WhatsApp Web page that OpenWA keeps open (headless: nothing is shown on screen).

This OpenWA build has no file sending of its own, so a small Node script (wa_voice.js) attaches to that same Chromium and uses
WhatsApp Web's attachment pipeline from inside the page, marking the audio as a voice note (push-to-talk)."""

import asyncio
import base64
import json
import os
import shutil
from collections.abc import Awaitable, Callable
from pathlib import Path

from .models import Outgoing
from .openwa import WhatsAppError

SCRIPT = Path(__file__).with_name("wa_voice.js")
Runner = Callable[[list[str], bytes], Awaitable[tuple[int, bytes]]]


async def _run(argv: list[str], stdin: bytes, timeout: float = 60.0) -> tuple[int, bytes]:
    try:
        process = await asyncio.create_subprocess_exec(*argv, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                                                       stderr=asyncio.subprocess.DEVNULL)
        out, _ = await asyncio.wait_for(process.communicate(stdin), timeout)
    except (OSError, asyncio.TimeoutError) as exc:
        raise WhatsAppError(f"could not run the voice sender: {exc}") from exc
    return process.returncode or 0, out


class WebVoiceSender:
    def __init__(self, openwa_home: str, node: str | None = None, run: Runner = _run, script: Path = SCRIPT):
        self._home = os.path.expanduser(openwa_home)
        bundled = Path(self._home) / "node_modules" / "node" / "bin" / "node"
        self._node = node or (str(bundled) if bundled.is_file() else shutil.which("node") or "node")
        self._run = run
        self._script = str(script)

    def _argv(self, mode: str) -> list[str]:
        return [self._node, self._script, self._home, mode]

    @staticmethod
    def _answer(code: int, out: bytes) -> dict:
        try:
            data = json.loads(out.decode("utf-8", "replace") or "{}")
        except ValueError:
            data = {}
        if code != 0 or not data.get("ok"):
            raise WhatsAppError(f"voice note not sent: {data.get('error') or 'the voice sender failed'}")
        return data

    async def available(self) -> bool | None:
        """True when the page can send voice notes; None when it could not be reached (OpenWA down, not logged in)."""
        if not (Path(self._home) / "run" / "_IGNORE_lite-agent" / "DevToolsActivePort").is_file():
            return None
        try:
            self._answer(*await self._run(self._argv("check"), b""))
        except WhatsAppError:
            return None
        return True

    async def send(self, chat_id: str, audio: bytes, mime: str) -> str:
        Outgoing(chat_id, "x")  # recipient check
        if not mime.startswith("audio/"):
            raise ValueError("not audio")
        body = json.dumps({"chatId": chat_id, "b64": base64.b64encode(audio).decode()}).encode()
        data = self._answer(*await self._run(self._argv("send"), body))
        return str(data.get("id", ""))
