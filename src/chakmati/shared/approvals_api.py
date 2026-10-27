"""The one approval inbox for every integration: what is waiting, approve, reject."""

import asyncio
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException

from chakmati.shared.approvals import Action, ActionExpired, ActionNotPending, ApprovalService, RateLimited
from chakmati.shared.http import ui_only


def action_json(a: Action) -> dict:
    return {
        "id": a.id, "kind": a.kind, "summary": a.summary, "status": a.status,
        "result": a.result, "error": a.error, "expires_at": a.expires_at,
        "voice": bool((a.payload or {}).get("voice")), "own": bool((a.payload or {}).get("own")),
        "auto_ok": bool((a.payload or {}).get("auto_ok")), "risk": str((a.payload or {}).get("risk") or ""),  # computer: can it be kept approved, and what kind it is  # an automation with a recording to listen to first
    }


HIDDEN_KINDS = {"call_log", "e2e_notification", "notification", "notification_template", "gp2", "protocol", "ciphertext",
                "broadcast_notification", "oversized", "debug", "unknown"}


def router(approval_services: Callable[[], list[ApprovalService]]) -> APIRouter:
    router = APIRouter()

    @router.get("/actions")
    async def pending_actions():
        items = []
        for service in approval_services():
            items.extend(await asyncio.to_thread(service.pending))
        return [action_json(a) for a in sorted(items, key=lambda a: a.expires_at)]

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
        return action_json(action)

    @router.post("/actions/{action_id}/approve", dependencies=[Depends(ui_only)])
    async def approve_action(action_id: str):
        return await decide(action_id, True)

    @router.post("/actions/{action_id}/reject", dependencies=[Depends(ui_only)])
    async def reject_action(action_id: str):
        return await decide(action_id, False)

    return router
