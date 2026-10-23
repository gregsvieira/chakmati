"""Client for the OpenWA "Easy API" (https://openwa.dev), the local HTTP server that drives WhatsApp Web.

Contract used, taken from the running server (GET /api) and its schema, and checked against a real session:
  GET  /health                        public; {"connected": bool, "session": {"state": "READY", "ready": bool}}
  GET  /api/chats/getAll              -> {"success": true, "data": [chat, ...]}
  GET  /api/messages/getAll?chatId=   -> {"success": true, "data": [message, ...]}
  POST /api/messages/sendText         {"to": "<id>", "content": "<text>", "options": {}}
Authentication is the X-API-Key header. Query parameters are validated with strict types, so booleans/numbers cannot
be sent as query strings: only `chatId` is passed and the server defaults are used (own messages included).
"""

import time
from datetime import datetime
from typing import Any

import httpx

from .models import Chat, Message, Outgoing, Status

_KNOWN_SUFFIXES = {"c.us", "lid", "g.us"}


class WhatsAppError(Exception):
    pass


class WhatsAppAuthError(WhatsAppError):
    pass


def _id_of(value: Any) -> str | None:
    """Ids come as plain strings or as {"_serialized": ...} / {"user": ..., "server": ...} objects."""
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        if isinstance(value.get("_serialized"), str) and value["_serialized"]:
            return value["_serialized"]
        if value.get("user") and value.get("server"):
            return f"{value['user']}@{value['server']}"
    return None


def _ts(value: Any) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    seconds = value / 1000 if value > 1e12 else value  # some fields are in milliseconds
    try:
        return datetime.fromtimestamp(seconds).astimezone()
    except (OverflowError, OSError, ValueError):
        return None


def _first_text(*values: Any) -> str | None:
    for v in values:
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def parse_chat(raw: Any) -> Chat | None:
    if not isinstance(raw, dict):
        return None
    chat_id = _id_of(raw.get("id"))
    if not chat_id or chat_id.rpartition("@")[2] not in _KNOWN_SUFFIXES:
        return None  # bots, newsletters, status/broadcast...
    suffix = chat_id.rpartition("@")[2]
    contact = raw.get("contact") if isinstance(raw.get("contact"), dict) else {}
    name = _first_text(
        raw.get("formattedTitle"), raw.get("name"), contact.get("name"), contact.get("pushname"),
        contact.get("formattedName"), contact.get("shortName"),
    ) or chat_id.partition("@")[0]
    is_group = suffix == "g.us" or raw.get("isGroup") is True
    phone: str | None = None
    if not is_group:
        if suffix == "c.us":
            phone = chat_id.partition("@")[0]
        else:
            number = _id_of(contact.get("phoneNumber"))
            if number and number.endswith("@c.us"):
                phone = number.partition("@")[0]
    unread = raw.get("unreadCount")
    mute = raw.get("muteExpiration")
    muted = isinstance(mute, int) and not isinstance(mute, bool) and (mute == -1 or mute > time.time())
    return Chat(chat_id, name, is_group, unread if isinstance(unread, int) and not isinstance(unread, bool) else 0,
                _ts(raw.get("t")), phone, archived=raw.get("archive") is True, muted=muted)


def parse_message(raw: Any) -> Message | None:
    if not isinstance(raw, dict):
        return None
    msg_id = _id_of(raw.get("id"))
    ts = _ts(raw.get("t"))
    if not msg_id or ts is None:
        return None
    kind = raw.get("type") if isinstance(raw.get("type"), str) and raw.get("type") else "chat"
    from_me = raw.get("fromMe") is True or msg_id.startswith("true_")
    # For anything that is not plain text, `body` can be a huge base64 blob: never use it as text.
    if kind == "chat":
        text = raw.get("body") if isinstance(raw.get("body"), str) else ""
    else:
        text = raw.get("caption") if isinstance(raw.get("caption"), str) else ""
    chat_id = _id_of(raw.get("chatId")) or _id_of(raw.get("to") if from_me else raw.get("from"))
    if not chat_id:
        return None
    sender_obj = raw.get("sender") if isinstance(raw.get("sender"), dict) else {}
    author = _id_of(raw.get("author")) or _id_of(raw.get("from")) or ""
    sender = "eu" if from_me else (
        _first_text(raw.get("notifyName"), sender_obj.get("pushname"), sender_obj.get("formattedName"))
        or author.partition("@")[0] or "?"
    )
    return Message(msg_id, chat_id, sender, text, ts, from_me, kind)


class OpenWAClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 60.0,
    ):
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._http = httpx.AsyncClient(transport=transport, timeout=timeout)

    async def _request(self, method: str, path: str, *, params=None, body=None, auth: bool = True) -> Any:
        headers = {"X-API-Key": self._key} if auth and self._key else {}
        try:
            response = await self._http.request(method, self._base + path, params=params, json=body, headers=headers)
        except httpx.HTTPError as exc:
            raise WhatsAppError(f"OpenWA unreachable at {self._base}: {exc}") from exc
        if response.status_code == 401:
            raise WhatsAppAuthError("OpenWA rejected the API key")
        if response.status_code >= 400:
            try:
                payload = response.json()
                detail = payload.get("error") or payload.get("message") or response.text[:200]
            except ValueError:
                detail = response.text[:200]
            raise WhatsAppError(f"OpenWA returned {response.status_code}: {detail}")
        data = response.json()
        if isinstance(data, dict) and data.get("success") is False:
            raise WhatsAppError(str(data.get("error") or "OpenWA reported a failure"))
        return data

    async def status(self) -> Status:
        health = await self._request("GET", "/health", auth=False)
        session = health.get("session") if isinstance(health.get("session"), dict) else {}
        return Status(bool(health.get("connected")), str(session.get("state", "")))

    async def list_chats(self, unread_only: bool = False, limit: int = 50) -> list[Chat]:
        data = (await self._request("GET", "/api/chats/getAll")).get("data") or []
        chats = [c for c in (parse_chat(r) for r in data) if c is not None]
        if unread_only:
            chats = [c for c in chats if c.unread > 0]
        chats.sort(key=lambda c: c.ts.timestamp() if c.ts else 0.0, reverse=True)
        return chats[:limit]

    async def get_messages(self, chat_id: str, last: int = 20) -> list[Message]:
        data = (await self._request("GET", "/api/messages/getAll", params={"chatId": chat_id})).get("data") or []
        messages = [m for m in (parse_message(r) for r in data) if m is not None]
        messages.sort(key=lambda m: m.ts)
        return messages[-last:] if last > 0 else []

    async def send_text(self, chat_id: str, text: str) -> str:
        out = Outgoing(chat_id, text)  # validates the recipient and the text
        data = await self._request("POST", "/api/messages/sendText",
                                   body={"to": out.to, "content": out.text, "options": {}})
        return str(data.get("data"))

    async def aclose(self) -> None:
        await self._http.aclose()
