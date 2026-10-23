import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress

from datetime import datetime

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from .agenda.models import CalendarEvent
from .agenda.service import Action, ActionExpired, ActionNotPending, CalendarService
from .engine import Engine
from .jobs import DONE, FAILED, JobStore, Worker


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


STREAM_POLL_SECONDS = 0.05
STREAM_MAX_SECONDS = 600.0
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _event_json(e: CalendarEvent) -> dict:
    return {
        "id": e.id, "title": e.title, "start": e.start.isoformat(), "end": e.end.isoformat(),
        "all_day": e.all_day, "location": e.location, "notes": e.notes, "calendar": e.calendar,
    }


def _action_json(a: Action) -> dict:
    return {
        "id": a.id, "kind": a.kind, "summary": a.summary, "status": a.status,
        "result": a.result, "error": a.error, "expires_at": a.expires_at,
    }


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def create_app(
    engine: Engine,
    store: JobStore,
    worker: Worker | None = None,
    on_startup: Callable[[], Awaitable[object]] | None = None,
    calendar: CalendarService | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = None
        startup_task = None
        if worker is not None:
            store.requeue_running()
            task = asyncio.create_task(worker.run_forever())
        if on_startup is not None:
            startup_task = asyncio.create_task(on_startup())  # background: never delays serving
        try:
            yield
        finally:
            for t in (task, startup_task):
                if t is not None:
                    t.cancel()
                    with suppress(asyncio.CancelledError):
                        await t

    app = FastAPI(lifespan=lifespan)

    async def job_events(job_id: str) -> AsyncIterator[dict]:
        """Follow a job: status changes, the text as it grows (delta), then done or error.
        The text comes from the job row (`partial`, then `result`), so a client that connects
        late, or reconnects, still receives everything from the beginning."""
        sent = 0
        last_status = None
        waited = 0.0
        while waited <= STREAM_MAX_SECONDS:
            job = store.get(job_id)
            if job is None:
                yield {"type": "error", "error": "job not found"}
                return
            if job.status != last_status:
                last_status = job.status
                yield {"type": "status", "status": job.status}
            text = job.result if job.status == DONE and job.result is not None else job.partial
            if len(text) > sent:
                yield {"type": "delta", "text": text[sent:]}
                sent = len(text)
            if job.status == DONE:
                yield {"type": "done", "result": job.result or ""}
                return
            if job.status == FAILED:
                yield {"type": "error", "error": job.error or "failed"}
                return
            await asyncio.sleep(STREAM_POLL_SECONDS)
            waited += STREAM_POLL_SECONDS
        yield {"type": "error", "error": "timeout waiting for the job"}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.post("/message")
    async def post_message(body: MessageIn):
        reply = await engine.handle(body.text)
        return {
            "kind": reply.kind,
            "route": reply.route.value,
            "text": reply.text,
            "job_id": reply.job_id,
        }

    @app.get("/jobs/{job_id}")
    async def get_job(job_id: str):
        job = store.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="job not found")
        return {
            "id": job.id,
            "route": job.route,
            "status": job.status,
            "result": job.result,
            "error": job.error,
            "partial": job.partial,
        }

    @app.get("/jobs/{job_id}/stream")
    async def stream_job(job_id: str):
        if store.get(job_id) is None:
            raise HTTPException(status_code=404, detail="job not found")

        async def body() -> AsyncIterator[str]:
            async for event in job_events(job_id):
                yield _sse(event)

        return StreamingResponse(body(), media_type="text/event-stream", headers=SSE_HEADERS)

    @app.post("/message/stream")
    async def post_message_stream(body: MessageIn):
        async def events() -> AsyncIterator[str]:
            async for event in engine.handle_stream(body.text):
                yield _sse(event)
                if event["type"] == "job":
                    async for job_event in job_events(event["job_id"]):
                        yield _sse(job_event)

        return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)

    # ------------------------------------------------------------------ calendar
    def need_calendar() -> CalendarService:
        if calendar is None:
            raise HTTPException(status_code=503, detail="calendar integration is disabled (LITEAGENT_CALENDAR_BACKEND)")
        return calendar

    def ui_only(x_liteagent_ui: str | None = Header(default=None)) -> None:
        # Writes are decided by the user's own UI. A custom header cannot be sent by a web page on another
        # origin without a CORS preflight, which this server never grants, so a random site cannot approve.
        if x_liteagent_ui != "1":
            raise HTTPException(status_code=403, detail="approval must come from the user interface (X-LiteAgent-UI: 1)")

    @app.get("/agenda/events")
    async def agenda_events(start: datetime, end: datetime):
        service = need_calendar()
        if start.tzinfo is None or end.tzinfo is None:
            raise HTTPException(status_code=422, detail="start and end must include a timezone")
        if end <= start:
            raise HTTPException(status_code=422, detail="end must be after start")
        events = await asyncio.to_thread(service.events, start, end)
        return [_event_json(e) for e in events]

    @app.get("/actions")
    async def pending_actions():
        service = need_calendar()
        return [_action_json(a) for a in await asyncio.to_thread(service.pending)]

    async def decide(action_id: str, approve: bool) -> dict:
        service = need_calendar()
        try:
            action = await asyncio.to_thread(service.approve if approve else service.reject, action_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="action not found") from None
        except ActionExpired:
            raise HTTPException(status_code=410, detail="the proposal expired") from None
        except ActionNotPending as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        return _action_json(action)

    @app.post("/actions/{action_id}/approve", dependencies=[Depends(ui_only)])
    async def approve_action(action_id: str):
        return await decide(action_id, True)

    @app.post("/actions/{action_id}/reject", dependencies=[Depends(ui_only)])
    async def reject_action(action_id: str):
        return await decide(action_id, False)

    return app
