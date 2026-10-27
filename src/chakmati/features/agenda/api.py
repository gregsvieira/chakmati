"""HTTP routes of the calendar."""

import asyncio
from datetime import datetime

from fastapi import APIRouter, HTTPException

from chakmati.features.agenda.models import CalendarEvent
from chakmati.features.agenda.service import CalendarService


def event_json(e: CalendarEvent) -> dict:
    return {
        "id": e.id, "title": e.title, "start": e.start.isoformat(), "end": e.end.isoformat(),
        "all_day": e.all_day, "location": e.location, "notes": e.notes, "calendar": e.calendar,
    }


def router(calendar: CalendarService | None) -> APIRouter:
    router = APIRouter()

    def need_calendar() -> CalendarService:
        if calendar is None:
            raise HTTPException(status_code=503, detail="calendar integration is disabled (CHAKMATI_CALENDAR_BACKEND)")
        return calendar

    @router.get("/agenda/events")
    async def agenda_events(start: datetime, end: datetime):
        service = need_calendar()
        if start.tzinfo is None or end.tzinfo is None:
            raise HTTPException(status_code=422, detail="start and end must include a timezone")
        if end <= start:
            raise HTTPException(status_code=422, detail="end must be after start")
        events = await asyncio.to_thread(service.events, start, end)
        return [event_json(e) for e in events]

    return router
