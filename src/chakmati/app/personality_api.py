"""HTTP routes of the personality: read it, and change it at once (the desktop's Ajustes does, with no restart)."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from chakmati.app.engine import Engine
from chakmati.shared import personality
from chakmati.shared.http import ui_only


class PersonalityIn(BaseModel):
    id: str


def router(engine: Engine) -> APIRouter:
    router = APIRouter()

    @router.get("/personality")
    async def get_personality():
        return {"current": engine.personality, "options": personality.options()}

    @router.put("/personality", dependencies=[Depends(ui_only)])
    async def set_personality(body: PersonalityIn):
        if not engine.set_personality(body.id):
            raise HTTPException(status_code=422, detail=f"unknown personality: {body.id}")
        return {"current": engine.personality}

    return router
