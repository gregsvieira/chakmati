"""Attaching files to the conversation: the app uploads the bytes, the engine keeps only the text, and the messages mention the id."""

from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request

from chakmati.features.files import reader
from chakmati.features.files.store import AttachmentStore
from chakmati.shared.http import ui_only


def router(store: AttachmentStore) -> APIRouter:
    router = APIRouter()

    @router.post("/attachments", dependencies=[Depends(ui_only)])
    async def attach(request: Request):
        name = reader.clean_name(unquote(request.headers.get("x-filename", "arquivo")))
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > reader.MAX_UPLOAD:
            raise HTTPException(status_code=413, detail="O arquivo é grande demais (o limite é 20 MB).")
        data = await request.body()
        try:
            attachment = store.add(name, data)
        except reader.UnreadableFile as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        return {"id": attachment.id, "name": attachment.name, "chars": attachment.chars}

    @router.delete("/attachments/{attachment_id}", dependencies=[Depends(ui_only)])
    async def detach(attachment_id: str):
        if not store.delete(attachment_id):
            raise HTTPException(status_code=404, detail="attachment not found")
        return {"ok": True}

    return router
