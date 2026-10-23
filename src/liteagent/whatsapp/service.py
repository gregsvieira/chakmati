"""WhatsApp reading and approved sending.

Reading is direct. Sending is only ever a PROPOSAL until the user approves it in the UI, and approved sends are
rate limited (per hour, and a minimum gap between sends) because bursts of automated messages are what gets a
WhatsApp number banned.
"""

import asyncio
import time
from collections import deque
from collections.abc import Awaitable, Callable

from ..approvals import Action, ActionStore, ApprovalService
from .models import Chat, Message, MessagingProvider, Outgoing, Status


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
    ):
        super().__init__(actions, ttl_seconds, now)
        self._provider = provider
        self._max = max_sends_per_hour
        self._min_interval = min_interval
        self._sleep = sleep
        self._sent_at: deque[float] = deque()

    # ---- reading (no approval needed)
    async def status(self) -> Status:
        return await self._provider.status()  # type: ignore[attr-defined]

    async def chats(self, unread_only: bool = False, limit: int = 50) -> list[Chat]:
        return await self._provider.list_chats(unread_only, limit)

    async def messages(self, chat_id: str, last: int = 20) -> list[Message]:
        return await self._provider.get_messages(chat_id, last)

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
