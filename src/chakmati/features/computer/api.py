"""HTTP routes of the computer assistant ("manter aprovado")."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from chakmati.shared.approvals import ApprovalService
from chakmati.shared.http import ui_only


def router(computer: ApprovalService | None) -> APIRouter:
    router = APIRouter()

    @router.get("/computer/standing")
    async def computer_standing():
        return {"standing": bool(getattr(computer, "standing", False))}

    class Standing(BaseModel):
        on: bool

    @router.post("/computer/standing", dependencies=[Depends(ui_only)])
    async def set_computer_standing(body: Standing):
        """"Manter aprovado": only safe commands and new files inside the workspace skip the question. Everything else always asks."""
        if computer is None:
            raise HTTPException(status_code=503, detail="computer actions are disabled")
        computer.standing = body.on
        return {"standing": computer.standing}

    return router
