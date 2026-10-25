import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager, suppress

from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field

from .agenda.models import CalendarEvent
from .agenda.service import Action, ActionExpired, ActionNotPending, CalendarService
from .approvals import ApprovalService
from . import extras
from .automations.audio import wav_to_ogg_opus_timed
from .automations.models import describe, parse_spec
from .automations.service import AutomationError, AutomationService
from .engine import Engine
from .jobs import DONE, FAILED, JobStore, Worker
from .notices import NoticeBoard, Notifier
from .persona import wake_reply
from .stt import SpeechToText, TranscribeError
from .tts import VoiceError, VoiceSynth
from .whatsapp.media import MediaError
from .whatsapp.openwa import WhatsAppError
from .whatsapp.service import RateLimited, WhatsAppService


class MessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    speed: str = "normal"


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
        "voice": bool((a.payload or {}).get("voice")), "own": bool((a.payload or {}).get("own")),
        "auto_ok": bool((a.payload or {}).get("auto_ok")), "risk": str((a.payload or {}).get("risk") or ""),  # computer: can it be kept approved, and what kind it is  # an automation with a recording to listen to first
    }


HIDDEN_KINDS = {"call_log", "e2e_notification", "notification", "notification_template", "gp2", "protocol", "ciphertext",
                "broadcast_notification", "oversized", "debug", "unknown"}


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def create_app(
    engine: Engine,
    store: JobStore,
    worker: Worker | None = None,
    on_startup: Callable[[], Awaitable[object]] | None = None,
    calendar: CalendarService | None = None,
    whatsapp: WhatsAppService | None = None,
    board: NoticeBoard | None = None,
    notifier: Notifier | None = None,
    stt: SpeechToText | None = None,
    tts: VoiceSynth | None = None,
    automations: AutomationService | None = None,
    home: ApprovalService | None = None,
    computer: ApprovalService | None = None,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = None
        startup_task = None
        if notifier is not None:
            notifier.start()
        if worker is not None:
            store.requeue_running()
            task = asyncio.create_task(worker.run_forever())
        if on_startup is not None:
            startup_task = asyncio.create_task(on_startup())  # background: never delays serving
        try:
            yield
        finally:
            if notifier is not None:
                await notifier.stop()
            for t in (task, startup_task):
                if t is not None:
                    t.cancel()
                    with suppress(asyncio.CancelledError):
                        await t

    app = FastAPI(lifespan=lifespan)
    app.state.notifier = notifier
    notices = board or NoticeBoard()

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

    # ---- one approval inbox for every integration
    def approval_services() -> list[ApprovalService]:
        services: list[ApprovalService] = [x for x in (calendar, whatsapp, automations, home, computer) if x is not None]
        if not services:
            raise HTTPException(status_code=503, detail="no integration is enabled (calendar or WhatsApp backend)")
        return services

    @app.get("/actions")
    async def pending_actions():
        items = []
        for service in approval_services():
            items.extend(await asyncio.to_thread(service.pending))
        return [_action_json(a) for a in sorted(items, key=lambda a: a.expires_at)]

    async def decide(action_id: str, approve: bool) -> dict:
        owner = next((s for s in approval_services() if s.owns(action_id)), None)
        if owner is None:
            raise HTTPException(status_code=404, detail="action not found")
        try:
            if approve:
                action = await owner.aapprove(action_id)  # async-native integrations run on the loop, the rest in a thread
            else:
                action = await asyncio.to_thread(owner.reject, action_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="action not found") from None
        except ActionExpired:
            raise HTTPException(status_code=410, detail="the proposal expired") from None
        except ActionNotPending as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except RateLimited as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from None
        return _action_json(action)

    # ---- whatsapp (reading; sending goes through /actions)
    def need_whatsapp() -> WhatsAppService:
        if whatsapp is None:
            raise HTTPException(status_code=503, detail="WhatsApp integration is disabled (LITEAGENT_WHATSAPP_BACKEND)")
        return whatsapp

    @app.get("/whatsapp/status")
    async def whatsapp_status():
        try:
            status = await need_whatsapp().status()
        except WhatsAppError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from None
        return {"connected": status.connected, "state": status.state}

    @app.get("/whatsapp/chats")
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

    @app.get("/whatsapp/chats/{chat_id}/messages", dependencies=[Depends(ui_only)])
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

    @app.get("/whatsapp/chats/{chat_id}/messages/{message_id}/audio", dependencies=[Depends(ui_only)])
    async def whatsapp_audio(chat_id: str, message_id: str):
        try:
            audio, mime = await need_whatsapp().audio(chat_id, message_id)
        except LookupError:
            raise HTTPException(status_code=404, detail="that message has no playable audio") from None
        except (WhatsAppError, MediaError) as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from None
        return Response(audio, media_type=mime, headers={"Cache-Control": "no-store"})

    @app.post("/transcribe", dependencies=[Depends(ui_only)])
    async def transcribe(request: Request):
        if stt is None:
            detail = "speech recognition is off (LITEAGENT_STT_MODEL)" if extras.available("listen") else extras.missing_message("listen", "speech recognition")
            raise HTTPException(status_code=503, detail=detail)
        if not (request.headers.get("content-type") or "").lower().startswith("audio/"):
            raise HTTPException(status_code=415, detail="send the recording with an audio/* content type")
        audio = await request.body()
        try:
            text, language = await asyncio.to_thread(stt.transcribe, audio)
        except TranscribeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        # `wake`: this is one of the wake phrases; `awake`: the assistant is already waiting for a command. The always-on
        # microphone acts only on those two, so ordinary talk in the room never reaches the model.
        return {"text": text, "language": language, "wake": wake_reply(text) is not None, "awake": engine.awake}

    # ---- the optional enhanced voice (downloaded on demand, spoken locally)
    def need_voice() -> VoiceSynth:
        if tts is None:
            raise HTTPException(status_code=503, detail="the enhanced voice is not available")
        return tts

    @app.get("/voice/status")
    async def voice_status():
        return {**need_voice().store.status(), "engine_ready": extras.available("voice")}

    @app.post("/voice/download", dependencies=[Depends(ui_only)])
    async def voice_download():
        store = need_voice().store
        if not store.installed() and not store.status()["downloading"]:
            app.state.voice_task = asyncio.create_task(store.download())  # runs in the background; poll /voice/status
            await asyncio.sleep(0)
        return store.status()

    @app.delete("/voice", dependencies=[Depends(ui_only)])
    async def voice_remove():
        store = need_voice().store
        if store.status()["downloading"]:
            raise HTTPException(status_code=409, detail="the voice is being downloaded")
        store.remove()
        return store.status()

    @app.post("/speak", dependencies=[Depends(ui_only)])
    async def speak(body: SpeakIn):
        synth = need_voice()
        if not synth.store.installed():
            raise HTTPException(status_code=409, detail="the enhanced voice is not installed yet")
        try:
            audio = await asyncio.to_thread(synth.synthesize, body.text, body.speed)
        except VoiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    # ---- automations (creating one goes through /actions like everything else)
    def need_automations() -> AutomationService:
        if automations is None:
            raise HTTPException(status_code=503, detail="automations are disabled")
        return automations

    def _automation_json(a) -> dict:
        return {"id": a.id, "name": a.name, "enabled": a.enabled, "description": describe(a.spec), "trigger": a.spec.trigger["type"], "channel": "whatsapp",
                "voice": a.spec.action["type"] == "whatsapp_voice", "runs": a.runs, "last_run_at": a.last_run_at}

    @app.get("/automations")
    async def list_automations():
        return [_automation_json(a) for a in await asyncio.to_thread(need_automations().store.list)]

    @app.post("/automations/{auto_id}/enable", dependencies=[Depends(ui_only)])
    async def enable_automation(auto_id: str):
        if not need_automations().store.set_enabled(auto_id, True):
            raise HTTPException(status_code=404, detail="automation not found")
        return {"ok": True}

    @app.post("/automations/{auto_id}/disable", dependencies=[Depends(ui_only)])
    async def disable_automation(auto_id: str):
        if not need_automations().store.set_enabled(auto_id, False):
            raise HTTPException(status_code=404, detail="automation not found")
        return {"ok": True}

    @app.delete("/automations/{auto_id}", dependencies=[Depends(ui_only)])
    async def delete_automation(auto_id: str):
        service = need_automations()
        if not service.store.delete(auto_id):
            raise HTTPException(status_code=404, detail="automation not found")
        service.recording_path(auto_id).unlink(missing_ok=True)
        return {"ok": True}

    MAX_RECORDING = 2 * 1024 * 1024
    MAX_RECORDING_SECONDS = 12

    @app.post("/automations/recorded", dependencies=[Depends(ui_only)])
    async def propose_recorded(request: Request):
        """A reply recorded by the person: becomes a PROPOSAL (nothing exists until they confirm) for "answer anyone who writes"."""
        service = need_automations()
        if not (request.headers.get("content-type") or "").lower().startswith("audio/"):
            raise HTTPException(status_code=415, detail="send the recording with an audio/* content type")
        audio = await request.body()
        if not audio or len(audio) > MAX_RECORDING:
            raise HTTPException(status_code=413, detail="the recording is empty or too large")
        try:
            ogg, seconds = await asyncio.to_thread(wav_to_ogg_opus_timed, audio)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        if seconds > MAX_RECORDING_SECONDS:
            raise HTTPException(status_code=422, detail="the recording is longer than 10 seconds")
        text = ""
        if stt is not None:  # the words only describe the automation in the list; what is sent is the recording itself
            with suppress(Exception):
                text, _ = await asyncio.to_thread(stt.transcribe, audio)
        text = text.strip()[:300] or "mensagem de voz gravada por você"
        spec = parse_spec({"name": "Resposta em áudio", "trigger": {"type": "whatsapp_message"},
                           "action": {"type": "whatsapp_voice", "to": "sender", "text": text, "own_voice": True}})
        try:
            await service.ensure_audio_possible()
            action = await asyncio.to_thread(service.propose_create, spec, ogg)
        except AutomationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        engine.expect_answer(60.0)
        return {**_action_json(action), "transcript": text}

    @app.get("/actions/{action_id}/preview", dependencies=[Depends(ui_only)])
    async def preview_action(action_id: str):
        audio = need_automations().preview(action_id)
        if audio is None:
            raise HTTPException(status_code=404, detail="no recording for this action")
        return Response(audio, media_type="audio/ogg", headers={"Cache-Control": "no-store"})

    @app.get("/computer/standing")
    async def computer_standing():
        return {"standing": bool(getattr(computer, "standing", False))}

    class Standing(BaseModel):
        on: bool

    @app.post("/computer/standing", dependencies=[Depends(ui_only)])
    async def set_computer_standing(body: Standing):
        """"Manter aprovado": only safe commands and new files inside the workspace skip the question. Everything else always asks."""
        if computer is None:
            raise HTTPException(status_code=503, detail="computer actions are disabled")
        computer.standing = body.on
        return {"standing": computer.standing}

    @app.post("/actions/{action_id}/approve", dependencies=[Depends(ui_only)])
    async def approve_action(action_id: str):
        return await decide(action_id, True)

    @app.post("/actions/{action_id}/reject", dependencies=[Depends(ui_only)])
    async def reject_action(action_id: str):
        return await decide(action_id, False)

    # ---- proactive notices and the overview the desktop panel shows
    @app.get("/notices")
    async def get_notices(after: int = 0, wait: float = Query(default=0.0, ge=0.0, le=60.0)):
        if after > notices.last_id:  # the client remembers ids from before an engine restart: start over
            after = 0
        found = await notices.wait_for(after, wait) if wait > 0 else notices.since(after)
        return {
            "notices": [{"id": n.id, "kind": n.kind, "text": n.text, "masked": n.masked, "ts": n.ts, "key": n.key} for n in found],
            "last_id": found[-1].id if found else notices.last_id,
        }

    @app.get("/overview")
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
                result["calendar"] = {"enabled": True, "today": [_event_json(e) for e in events]}
            except Exception as exc:  # a calendar problem must not hide the other sections
                result["calendar"] = {"enabled": True, "error": f"{type(exc).__name__}: {exc}"}
        pending = []
        for service in [x for x in (calendar, whatsapp, automations, home, computer) if x is not None]:
            pending.extend(await asyncio.to_thread(service.pending))
        result["pending"] = [_action_json(a) for a in sorted(pending, key=lambda a: a.expires_at)]
        if automations is not None:
            result["automations"] = [_automation_json(a) for a in await asyncio.to_thread(automations.store.list)]
        result["home"] = {"enabled": home is not None}
        result["computer_standing"] = bool(getattr(computer, "standing", False))
        result["last_notice_id"] = notices.last_id
        result["awake"] = engine.awake
        result["awake_for"] = round(engine.awake_for, 1)
        return result

    return app
