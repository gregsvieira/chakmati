"""What the desktop panel reads: the proactive notices and the overview of every integration."""

import asyncio
from datetime import datetime, timedelta

from fastapi import APIRouter, Query

from chakmati.app.engine import Engine
from chakmati.features.agenda.api import event_json
from chakmati.features.agenda.service import CalendarService
from chakmati.features.automations.api import automation_json
from chakmati.features.automations.service import AutomationService
from chakmati.features.whatsapp.openwa import WhatsAppError
from chakmati.features.whatsapp.service import WhatsAppService
from chakmati.shared.approvals import ApprovalService
from chakmati.shared.approvals_api import action_json
from chakmati.shared.notices import NoticeBoard


def router(engine: Engine, notices: NoticeBoard, calendar: CalendarService | None, whatsapp: WhatsAppService | None,
           automations: AutomationService | None, home: ApprovalService | None, computer: ApprovalService | None, home_link=None) -> APIRouter:
    router = APIRouter()

    @router.get("/notices")
    async def get_notices(after: int = 0, wait: float = Query(default=0.0, ge=0.0, le=60.0)):
        if after > notices.last_id:  # the client remembers ids from before an engine restart: start over
            after = 0
        found = await notices.wait_for(after, wait) if wait > 0 else notices.since(after)
        return {
            "notices": [{"id": n.id, "kind": n.kind, "text": n.text, "masked": n.masked, "ts": n.ts, "key": n.key} for n in found],
            "last_id": found[-1].id if found else notices.last_id,
        }

    @router.get("/overview")
    async def overview():
        result: dict = {"whatsapp": {"enabled": whatsapp is not None}, "calendar": {"enabled": calendar is not None}}
        if whatsapp is not None:
            try:
                status = await whatsapp.status()
                section = {"enabled": True, "connected": status.connected, "state": status.state, "unread": [],
                           "media": await whatsapp.media_supported() if status.connected else None}
                if status.connected:
                    unread = await whatsapp.chats(unread_only=True, limit=20)
                    section["unread"] = [
                        {"id": c.id, "name": c.name, "unread": c.unread, "is_group": c.is_group} for c in unread
                    ]
                result["whatsapp"] = section
            except WhatsAppError as exc:
                result["whatsapp"] = {"enabled": True, "error": str(exc)}
        if calendar is not None:
            try:
                start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
                events = await asyncio.to_thread(calendar.events, start, start + timedelta(days=1))
                result["calendar"] = {"enabled": True, "today": [event_json(e) for e in events]}
            except Exception as exc:  # a calendar problem must not hide the other sections
                result["calendar"] = {"enabled": True, "error": f"{type(exc).__name__}: {exc}"}
        pending = []
        for service in [x for x in (calendar, whatsapp, automations, home, computer) if x is not None]:
            pending.extend(await asyncio.to_thread(service.pending))
        result["pending"] = [action_json(a) for a in sorted(pending, key=lambda a: a.expires_at)]
        if automations is not None:
            result["automations"] = [automation_json(a) for a in await asyncio.to_thread(automations.store.list)]
        result["home"] = {"enabled": home is not None, **(await home_link.status() if home_link is not None and home is not None else {})}
        result["computer_standing"] = bool(getattr(computer, "standing", False))
        result["last_notice_id"] = notices.last_id
        result["personality"] = engine.personality
        result["pronouns"] = engine.pronouns
        result["awake"] = engine.awake
        result["awake_for"] = round(engine.awake_for, 1)
        return result

    return router
