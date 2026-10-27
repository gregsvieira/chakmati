"""The engine's HTTP application: it builds the services' routers and mounts them. Each feature owns its own routes (features/<name>/api.py)."""

import asyncio
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, HTTPException

from chakmati.app import chat_api, overview
from chakmati.app.engine import Engine
from chakmati.features.agenda import api as agenda_api
from chakmati.features.agenda.service import CalendarService
from chakmati.features.automations import api as automations_api
from chakmati.features.automations.service import AutomationService
from chakmati.features.browser.frames import FrameStore
from chakmati.features.browser.inputs import InputBroker
from chakmati.features.computer import api as computer_api
from chakmati.features.whatsapp import api as whatsapp_api
from chakmati.features.whatsapp.service import WhatsAppService
from chakmati.shared import approvals_api
from chakmati.shared.approvals import ApprovalService
from chakmati.shared.jobs import JobStore, Worker
from chakmati.shared.notices import NoticeBoard, Notifier
from chakmati.shared.voice import api as voice_api
from chakmati.shared.voice.stt import SpeechToText
from chakmati.shared.voice.tts import VoiceSynth


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
    frames: FrameStore | None = None,
    inputs: InputBroker | None = None,
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

    def approval_services() -> list[ApprovalService]:
        services: list[ApprovalService] = [x for x in (calendar, whatsapp, automations, home, computer) if x is not None]
        if not services:
            raise HTTPException(status_code=503, detail="no integration is enabled (calendar or WhatsApp backend)")
        return services

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.include_router(chat_api.router(engine, store, worker, frames, inputs))
    app.include_router(agenda_api.router(calendar))
    app.include_router(approvals_api.router(approval_services))
    app.include_router(whatsapp_api.router(whatsapp))
    app.include_router(voice_api.router(stt, tts, lambda: engine.awake))
    app.include_router(automations_api.router(automations, stt, engine.expect_answer))
    app.include_router(computer_api.router(computer))
    app.include_router(overview.router(engine, notices, calendar, whatsapp, automations, home, computer))
    return app
