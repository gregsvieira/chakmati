"""WhatsApp reading and approved sending.

Reading is direct. Sending is only ever a PROPOSAL until the user approves it in the UI, and approved sends are
rate limited (per hour, and a minimum gap between sends) because bursts of automated messages are what gets a
WhatsApp number banned.
"""

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable

import httpx

from chakmati.shared.approvals import Action, ActionStore, ApprovalService
from chakmati.features.whatsapp.media import fetch_audio
from chakmati.features.whatsapp.models import Chat, Message, MessagingProvider, Outgoing, Status
from chakmati.features.whatsapp.openwa import WhatsAppError


class RateLimited(Exception):
    """Too many sends in the last hour. The proposal stays pending and can be approved later."""


class WhatsAppService(ApprovalService):
    prefix = "whatsapp."

    def __init__(
        self,
        provider: MessagingProvider,
        actions: ActionStore,
        ttl_seconds: float = 3600.0,
        now: Callable[[], float] = time.time,
        max_sends_per_hour: int = 20,
        min_interval: float = 3.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        audio_client_factory: Callable[[], httpx.AsyncClient] = lambda: httpx.AsyncClient(timeout=30.0),
    ):
        super().__init__(actions, ttl_seconds, now)
        self._provider = provider
        self._max = max_sends_per_hour
        self._min_interval = min_interval
        self._sleep = sleep
        self._audio_client_factory = audio_client_factory
        self._sent_at: deque[float] = deque()

    # ---- reading (no approval needed)
    async def status(self) -> Status:
        return await self._provider.status()  # type: ignore[attr-defined]

    async def chats(self, unread_only: bool = False, limit: int = 50) -> list[Chat]:
        return await self._provider.list_chats(unread_only, limit)

    async def messages(self, chat_id: str, last: int = 20) -> list[Message]:
        return await self._provider.get_messages(chat_id, last)

    async def audio(self, chat_id: str, message_id: str) -> tuple[bytes, str]:
        """The decrypted voice note, or LookupError when that message has none to play."""
        found = next((m for m in await self._provider.get_messages(chat_id, 500) if m.id == message_id), None)
        if found is None or found.media is None:
            raise LookupError("no playable audio in that message")
        async with self._audio_client_factory() as client:  # a plain client: the OpenWA key must not reach WhatsApp's CDN
            return await fetch_audio(found.media, client)

    MEDIA_RECHECK_SECONDS = 600.0

    async def media_supported(self) -> bool | None:
        """Whether voice notes can be sent at all (an OpenWA build may lack file sending). Cached for a while."""
        known = getattr(self, "_media", None)
        if known is not None and self._now() - known[1] < self.MEDIA_RECHECK_SECONDS:
            return known[0]
        check = getattr(self._provider, "supports_media", None)
        value = await check() if check is not None else True
        if value is not None:
            self._media = (value, self._now())
        return value

    # ---- sending without a per-message approval: only for automations the person confirmed when creating them
    MAX_AUDIO_BYTES = 5 * 1024 * 1024

    async def send_automated(self, chat_id: str, chat_name: str, text: str | None = None, audio: bytes | None = None,
                             mime: str | None = None, source: str = "") -> str:
        """Send what an automation was created to send. Same hourly limit and gap as approved sends, and every send
        leaves a row in the action log (kind whatsapp.auto, already executed) so there is always a trail."""
        if audio is None and text is None:
            raise ValueError("nothing to send: give a text or an audio")
        if audio is not None:
            if await self.media_supported() is False:
                raise WhatsAppError("o OpenWA instalado não consegue enviar áudio")
            Outgoing(chat_id, "x")  # recipient check
            if len(audio) > self.MAX_AUDIO_BYTES or not (mime or "").startswith("audio/"):
                raise ValueError("the audio is too large or is not audio")
            what = "áudio"
        else:
            out = Outgoing(chat_id, text)  # raises ValueError for a bad recipient, empty/oversized text, control characters
            chat_id, text, what = out.to, out.text, "mensagem"
        if self._recent_sends() >= self._max:
            raise RateLimited(f"limite de {self._max} envios por hora atingido")
        if self._sent_at:
            wait = self._min_interval - (self._now() - self._sent_at[-1])
            if wait > 0:
                await self._sleep(wait)
        self._sent_at.append(self._now())
        record = self._propose("whatsapp.auto", f"Envio automático ({what}) para {chat_name}", {"chat_id": chat_id, "chat_name": chat_name, "source": source, "kind": what})
        try:
            message_id = await (self._provider.send_voice(chat_id, audio, mime or "audio/ogg") if audio is not None else self._provider.send_text(chat_id, text))  # type: ignore[arg-type]
        except Exception as exc:
            self._record(record.id, None, exc)
            raise
        self._record(record.id, f"enviado (id {message_id})", None)
        return message_id

    # ---- proposing
    def propose_send(self, chat: Chat, text: str) -> Action:
        out = Outgoing(chat.id, text)  # raises ValueError for a bad recipient, empty/oversized text, control chars
        payload = {"chat_id": out.to, "chat_name": chat.name, "is_group": chat.is_group, "text": out.text}
        for existing in self.pending():  # asking twice for the same message must not queue it twice
            if existing.kind == "whatsapp.send" and existing.payload == payload:
                return existing
        summary = f"Enviar WhatsApp para {chat.label()}:\n{out.text}"
        return self._propose("whatsapp.send", summary, payload)

    # ---- executing (only after the user approved)
    def _recent_sends(self) -> int:
        horizon = self._now() - 3600
        while self._sent_at and self._sent_at[0] < horizon:
            self._sent_at.popleft()
        return len(self._sent_at)

    async def _aprecheck(self, action: Action) -> None:
        if action.kind == "whatsapp.send" and self._recent_sends() >= self._max:
            raise RateLimited(f"limite de {self._max} envios por hora atingido; aprove de novo mais tarde")

    async def _aexecute(self, action: Action) -> str:
        if action.kind != "whatsapp.send":
            raise ValueError(f"unknown action kind {action.kind}")
        if self._sent_at:
            wait = self._min_interval - (self._now() - self._sent_at[-1])
            if wait > 0:
                await self._sleep(wait)
        self._sent_at.append(self._now())  # counted as soon as we try: a failed send may still have gone out
        payload = action.payload
        message_id = await self._provider.send_text(payload["chat_id"], payload["text"])
        return f"Mensagem enviada para {payload['chat_name']} (id {message_id})"
