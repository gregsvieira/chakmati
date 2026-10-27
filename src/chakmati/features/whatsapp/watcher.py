"""Announces new WhatsApp messages on the notice board."""

import logging

from chakmati.features.whatsapp.openwa import WhatsAppError
from chakmati.shared.notices import NoticeBoard

log = logging.getLogger(__name__)


class WhatsAppWatcher:
    """Announces new unread messages. The first poll is only a baseline (plus one summary), so starting the app
    does not replay every old unread chat. Muted and archived chats stay silent, as they do on the phone."""

    def __init__(self, service, board: NoticeBoard, interval: float = 10.0, announce_connection: bool = True, on_fresh=None):
        self._service = service
        self._on_fresh = on_fresh  # async callable(list[(chat, delta)]): lets automations react to new messages
        self._board = board
        self.interval = interval
        self._announce_connection = announce_connection  # False when the live event stream already says it
        self._seen: dict[str, int] | None = None
        self._down = False

    async def poll_once(self) -> None:
        try:
            chats = await self._service.chats(limit=500)
        except WhatsAppError:
            if not self._down:
                self._down = True
                if self._announce_connection:
                    self._board.add("system", "O WhatsApp está desconectado. Abra o OpenWA e escaneie o QR.",
                                    "O WhatsApp está desconectado.")
            return
        if self._down:
            self._down = False
            if self._announce_connection:
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
        if self._on_fresh is not None:
            try:
                await self._on_fresh(fresh)
            except Exception:  # an automation must never break the notices
                log.warning("automation hook failed", exc_info=True)
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
