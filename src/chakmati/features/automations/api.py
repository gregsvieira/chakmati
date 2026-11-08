"""HTTP routes of automations (creating one goes through the approval inbox like everything else)."""

import asyncio
from collections.abc import Callable
from contextlib import suppress

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from chakmati.features.automations.audio import wav_to_ogg_opus_timed
from chakmati.features.automations.models import SpecError, describe, parse_spec
from chakmati.features.automations.service import AutomationError, AutomationService
from chakmati.shared.approvals_api import action_json
from chakmati.shared.http import ui_only
from chakmati.shared.voice.stt import SpeechToText


def automation_json(a) -> dict:
    return {"id": a.id, "name": a.name, "enabled": a.enabled, "description": describe(a.spec), "trigger": a.spec.trigger["type"], "channel": "home" if a.spec.action["type"] == "home_steps" else "whatsapp",
            "voice": a.spec.action["type"] == "whatsapp_voice", "runs": a.runs, "last_run_at": a.last_run_at}


MAX_RECORDING = 2 * 1024 * 1024
MAX_RECORDING_SECONDS = 12


def router(automations: AutomationService | None, stt: SpeechToText | None, expect_answer: Callable[[float], None]) -> APIRouter:
    """`expect_answer(seconds)`: tells the chat that the next thing the person says is the answer to the proposal just made."""
    router = APIRouter()

    # ---- automations (creating one goes through /actions like everything else)
    def need_automations() -> AutomationService:
        if automations is None:
            raise HTTPException(status_code=503, detail="automations are disabled")
        return automations

    @router.get("/automations")
    async def list_automations():
        return [automation_json(a) for a in await asyncio.to_thread(need_automations().store.list)]

    @router.post("/automations/{auto_id}/enable", dependencies=[Depends(ui_only)])
    async def enable_automation(auto_id: str):
        if not need_automations().store.set_enabled(auto_id, True):
            raise HTTPException(status_code=404, detail="automation not found")
        return {"ok": True}

    @router.post("/automations/{auto_id}/disable", dependencies=[Depends(ui_only)])
    async def disable_automation(auto_id: str):
        if not need_automations().store.set_enabled(auto_id, False):
            raise HTTPException(status_code=404, detail="automation not found")
        return {"ok": True}

    @router.delete("/automations/{auto_id}", dependencies=[Depends(ui_only)])
    async def delete_automation(auto_id: str):
        service = need_automations()
        if not service.store.delete(auto_id):
            raise HTTPException(status_code=404, detail="automation not found")
        service.recording_path(auto_id).unlink(missing_ok=True)
        return {"ok": True}

    @router.post("/automations/recorded", dependencies=[Depends(ui_only)])
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
        trigger: dict = {"type": "whatsapp_message"}
        start, end = request.query_params.get("hours_from"), request.query_params.get("hours_to")
        if start or end:   # the hours the automation works (the suggestion buttons of the panel): checked by parse_spec like any other
            trigger["hours"] = {"from": start, "to": end}
        try:
            spec = parse_spec({"name": "Resposta em áudio", "trigger": trigger,
                               "action": {"type": "whatsapp_voice", "to": "sender", "text": text, "own_voice": True}})
        except SpecError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        try:
            await service.ensure_audio_possible()
            action = await asyncio.to_thread(service.propose_create, spec, ogg)
        except AutomationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        expect_answer(60.0)
        return {**action_json(action), "transcript": text}

    @router.get("/actions/{action_id}/preview", dependencies=[Depends(ui_only)])
    async def preview_action(action_id: str):
        audio = need_automations().preview(action_id)
        if audio is None:
            raise HTTPException(status_code=404, detail="no recording for this action")
        return Response(audio, media_type="audio/ogg", headers={"Cache-Control": "no-store"})

    return router
