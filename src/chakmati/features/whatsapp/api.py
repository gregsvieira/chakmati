"""HTTP routes of WhatsApp (reading; sending goes through the approval inbox)."""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

from chakmati.features.whatsapp.media import MediaError
from chakmati.features.whatsapp.openwa import WhatsAppError
from chakmati.features.whatsapp.service import RateLimited, WhatsAppService
from chakmati.shared.http import ui_only

class SendBody(BaseModel):
    text: str


HIDDEN_KINDS = {"call_log", "e2e_notification", "notification", "notification_template", "gp2", "protocol", "ciphertext",
                "broadcast_notification", "oversized", "debug", "unknown"}


def router(whatsapp: WhatsAppService | None) -> APIRouter:
    router = APIRouter()

    def need_whatsapp() -> WhatsAppService:
        if whatsapp is None:
            raise HTTPException(status_code=503, detail="WhatsApp integration is disabled (CHAKMATI_WHATSAPP_BACKEND)")
        return whatsapp

    @router.get("/whatsapp/status")
    async def whatsapp_status():
        try:
            status = await need_whatsapp().status()
        except WhatsAppError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from None
        return {"connected": status.connected, "state": status.state}

    @router.get("/whatsapp/chats")
    async def whatsapp_chats(unread: bool = False, limit: int = 50):
        try:
            chats = await need_whatsapp().chats(unread_only=unread, limit=max(1, min(limit, 500)))
        except WhatsAppError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from None
        return [
            {"id": c.id, "name": c.name, "is_group": c.is_group, "unread": c.unread, "phone": c.phone,
             "last": c.ts.isoformat() if c.ts else None}
            for c in chats
        ]

    @router.get("/whatsapp/chats/{chat_id}/messages", dependencies=[Depends(ui_only)])
    async def whatsapp_messages(chat_id: str, last: int = 40):
        try:
            messages = await need_whatsapp().messages(chat_id, 500)
        except WhatsAppError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from None
        # WhatsApp also stores call records, encryption notices and group events in a chat: not part of the conversation
        messages = [m for m in messages if m.kind not in HIDDEN_KINDS][-max(1, min(last, 200)):]
        return [
            {"id": m.id, "sender": m.sender, "text": m.text, "ts": m.ts.isoformat(), "from_me": m.from_me, "kind": m.kind,
             "duration": m.duration, "audio": m.media is not None}  # the media key and URL stay inside the engine
            for m in messages
        ]

    @router.get("/whatsapp/chats/{chat_id}/messages/{message_id}/audio", dependencies=[Depends(ui_only)])
    async def whatsapp_audio(chat_id: str, message_id: str):
        try:
            audio, mime = await need_whatsapp().audio(chat_id, message_id)
        except LookupError:
            raise HTTPException(status_code=404, detail="that message has no playable audio") from None
        except (WhatsAppError, MediaError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from None
        return Response(audio, media_type=mime, headers={"Cache-Control": "no-store"})

    @router.post("/whatsapp/chats/{chat_id}/send", dependencies=[Depends(ui_only)])
    async def whatsapp_send(chat_id: str, body: SendBody):
        """The person's own message, typed in the panel's reply box. Only the app's window may call it (ui_only)."""
        service = need_whatsapp()
        try:
            chats = await service.chats(limit=500)
            chat = next((c for c in chats if c.id == chat_id), None)
            message_id = await service.send_direct(chat_id, chat.name if chat else chat_id, body.text)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except RateLimited as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from None
        except WhatsAppError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from None
        return {"ok": True, "id": message_id}

    return router
