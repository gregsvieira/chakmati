"""HTTP routes of the conversation: a message (plain or streamed), and the jobs it starts (state, stream, screenshots, questions, Parar)."""

import asyncio
import re
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from chakmati.app.engine import Engine
from chakmati.features.browser.frames import FrameStore
from chakmati.features.browser.inputs import InputBroker, MAX_ANSWER
from chakmati.shared.http import SSE_HEADERS, sse, ui_only
from chakmati.shared.jobs import CANCELLED, DONE, FAILED, JobStore, Worker


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)
    attachments: list[Annotated[str, Field(pattern=r"^[0-9a-f]{32}$")]] = Field(default_factory=list, max_length=5)  # ids of attached files


STREAM_POLL_SECONDS = 0.05
STREAM_MAX_SECONDS = 600.0


def router(engine: Engine, store: JobStore, worker: Worker | None, frames: FrameStore | None, inputs: InputBroker | None) -> APIRouter:
    router = APIRouter()

    async def job_events(job_id: str) -> AsyncIterator[dict]:
        """Follow a job: status changes, the text as it grows (delta), then done or error.
        The text comes from the job row (`partial`, then `result`), so a client that connects
        late, or reconnects, still receives everything from the beginning."""
        sent = 0
        frames_sent = 0
        asked = None  # the question of the browser agent that the client has been told about
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
            if frames is not None:  # the browser's screenshots, one event per step, as they are taken
                for frame in frames.list(job_id)[frames_sent:]:
                    yield {"type": "screenshot", "job_id": job_id, **frame}
                    frames_sent += 1
            if inputs is not None:  # the agent is waiting for something only the person can say (a user name, a password)
                waiting = inputs.pending(job_id)
                if waiting is not None and waiting.id != asked:
                    asked = waiting.id
                    yield {"type": "input", "job_id": job_id, "request_id": waiting.id, "key": waiting.key, "prompt": waiting.prompt, "secret": waiting.secret, "confirm": waiting.confirm}
                elif waiting is None and asked is not None:
                    yield {"type": "input_done", "request_id": asked}
                    asked = None
            text = job.result if job.status == DONE and job.result is not None else job.partial
            if len(text) > sent:
                yield {"type": "delta", "text": text[sent:]}
                sent = len(text)
            if job.status == DONE:
                yield {"type": "done", "result": job.result or ""}
                return
            if job.status == FAILED:
                if job.error == CANCELLED:
                    yield {"type": "cancelled", "text": CANCELLED}
                else:
                    yield {"type": "error", "error": job.error or "failed"}
                return
            await asyncio.sleep(STREAM_POLL_SECONDS)
            waited += STREAM_POLL_SECONDS
        yield {"type": "error", "error": "timeout waiting for the job"}

    @router.post("/message")
    async def post_message(body: MessageIn):
        reply = await engine.handle(body.text, body.attachments)
        return {
            "kind": reply.kind,
            "route": reply.route.value,
            "text": reply.text,
            "job_id": reply.job_id,
        }

    @router.get("/jobs/{job_id}")
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

    @router.get("/jobs/{job_id}/frames/{step}")
    async def get_frame(job_id: str, step: int):
        path = frames.path(job_id, step) if frames is not None and re.fullmatch(r"[0-9a-f]{32}", job_id) else None
        if path is None:
            raise HTTPException(status_code=404, detail="frame not found")
        return Response(path.read_bytes(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    class InputIn(BaseModel):
        request_id: str = Field(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$")
        value: str = Field(max_length=MAX_ANSWER)

    @router.post("/jobs/{job_id}/input", dependencies=[Depends(ui_only)])
    async def answer_input(job_id: str, body: InputIn):
        """The person's answer to a question of the browser agent. Only the app's own window may send it; the value is not stored or logged."""
        if inputs is None or not re.fullmatch(r"[0-9a-f]{32}", job_id) or not inputs.answer(job_id, body.request_id, body.value):
            raise HTTPException(status_code=404, detail="nothing is waiting for an answer")
        return {"ok": True}

    @router.post("/jobs/{job_id}/cancel", dependencies=[Depends(ui_only)])
    async def cancel_job(job_id: str):
        """The person pressed Parar: the job stops where it is. Only the app's own window may ask."""
        if not re.fullmatch(r"[0-9a-f]{32}", job_id) or store.get(job_id) is None:
            raise HTTPException(status_code=404, detail="job not found")
        stopped = worker.cancel(job_id) if worker is not None else False
        return {"ok": stopped}

    @router.get("/jobs/{job_id}/stream")
    async def stream_job(job_id: str):
        if store.get(job_id) is None:
            raise HTTPException(status_code=404, detail="job not found")

        async def body() -> AsyncIterator[str]:
            async for event in job_events(job_id):
                yield sse(event)

        return StreamingResponse(body(), media_type="text/event-stream", headers=SSE_HEADERS)

    @router.post("/message/stream")
    async def post_message_stream(body: MessageIn):
        async def events() -> AsyncIterator[str]:
            async for event in engine.handle_stream(body.text, body.attachments):
                yield sse(event)
                if event["type"] == "job":
                    async for job_event in job_events(event["job_id"]):
                        yield sse(job_event)

        return StreamingResponse(events(), media_type="text/event-stream", headers=SSE_HEADERS)

    return router
