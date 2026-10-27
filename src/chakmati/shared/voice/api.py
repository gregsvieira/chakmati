"""HTTP routes of speech: recognition (microphone) and the optional enhanced voice."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field

from chakmati.shared import extras
from chakmati.shared.http import ui_only
from chakmati.shared.persona import wake_reply
from chakmati.shared.voice.stt import SpeechToText, TranscribeError
from chakmati.shared.voice.tts import VoiceError, VoiceSynth


class SpeakIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    speed: str = "normal"


def router(stt: SpeechToText | None, tts: VoiceSynth | None, is_awake) -> APIRouter:
    """`is_awake()`: whether the assistant is already waiting for a command (the always-on microphone acts only then or on a wake phrase)."""
    router = APIRouter()

    @router.post("/transcribe", dependencies=[Depends(ui_only)])
    async def transcribe(request: Request):
        if stt is None:
            detail = "speech recognition is off (CHAKMATI_STT_MODEL)" if extras.available("listen") else extras.missing_message("listen", "speech recognition")
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
        return {"text": text, "language": language, "wake": wake_reply(text) is not None, "awake": is_awake()}

    # ---- the optional enhanced voice (downloaded on demand, spoken locally)
    def need_voice() -> VoiceSynth:
        if tts is None:
            raise HTTPException(status_code=503, detail="the enhanced voice is not available")
        return tts

    @router.get("/voice/status")
    async def voice_status():
        return {**need_voice().store.status(), "engine_ready": extras.available("voice")}

    @router.post("/voice/download", dependencies=[Depends(ui_only)])
    async def voice_download(request: Request):
        store = need_voice().store
        if not store.installed() and not store.status()["downloading"]:
            request.app.state.voice_task = asyncio.create_task(store.download())  # runs in the background; poll /voice/status
            await asyncio.sleep(0)
        return store.status()

    @router.delete("/voice", dependencies=[Depends(ui_only)])
    async def voice_remove():
        store = need_voice().store
        if store.status()["downloading"]:
            raise HTTPException(status_code=409, detail="the voice is being downloaded")
        store.remove()
        return store.status()

    @router.post("/speak", dependencies=[Depends(ui_only)])
    async def speak(body: SpeakIn):
        synth = need_voice()
        if not synth.store.installed():
            raise HTTPException(status_code=409, detail="the enhanced voice is not installed yet")
        try:
            audio = await asyncio.to_thread(synth.synthesize, body.text, body.speed)
        except VoiceError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})

    return router
