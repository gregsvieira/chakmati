import base64
import hashlib
import os
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from chakmati.api import create_app
from chakmati.approvals import ActionStore
from chakmati.engine import Engine
from chakmati.gate.base import GateResult, Route
from chakmati.jobs import JobStore
from chakmati.whatsapp.models import Chat, MediaRef, Message, Status
from chakmati.whatsapp.service import WhatsAppService

from .test_media import KEY, PLAIN, encrypt_audio

TS = datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc)
UI = {"X-LiteAgent-UI": "1"}
CHAT = "162457238634742@lid"
BLOB = encrypt_audio(PLAIN, KEY)
REF = MediaRef("https://mmg.whatsapp.net/v/x", base64.b64encode(KEY).decode(),
               base64.b64encode(hashlib.sha256(BLOB).digest()).decode(), "audio/ogg; codecs=opus")


class FakeGate:
    def classify(self, text):
        return GateResult(Route.CHAT, 1.0, "fake")


class FakeLLM:
    async def chat(self, messages):
        return "x"


class FakeProvider:
    async def status(self):
        return Status(True, "READY")

    async def list_chats(self, unread_only=False, limit=50):
        return [Chat(CHAT, "Maria Victoria", False, 3, TS)]

    async def get_messages(self, chat_id, last=20):
        return [
            Message("m1", chat_id, "Maria Victoria", "oi, tudo bem?", TS, False),
            Message("m2", chat_id, "Maria Victoria", "", TS, False, "ptt", 25, REF),
            Message("m3", chat_id, "Maria Victoria", "", TS, False, "ptt", 3, None),
            Message("m4", chat_id, "eu", "ok", TS, True),
        ][-last:]


@pytest.fixture
def client():
    store = JobStore(":memory:")
    audio_http = lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=BLOB)))  # noqa: E731
    wa = WhatsAppService(FakeProvider(), ActionStore(":memory:"), audio_client_factory=audio_http)
    return TestClient(create_app(Engine(FakeGate(), FakeLLM(), store), store, whatsapp=wa))


def test_messages_list_describes_text_and_voice_notes(client):
    r = client.get(f"/whatsapp/chats/{CHAT}/messages", headers=UI)
    assert r.status_code == 200
    items = r.json()
    assert [i["id"] for i in items] == ["m1", "m2", "m3", "m4"]
    assert items[0] == {"id": "m1", "sender": "Maria Victoria", "text": "oi, tudo bem?", "ts": TS.isoformat(),
                        "from_me": False, "kind": "chat", "duration": None, "audio": False}
    assert items[1]["kind"] == "ptt" and items[1]["duration"] == 25 and items[1]["audio"] is True
    assert items[2]["audio"] is False  # a voice note without download details cannot be played
    assert "media" not in items[1] and "key" not in str(items[1])  # keys never leave the engine


def test_messages_list_honours_last(client):
    assert [i["id"] for i in client.get(f"/whatsapp/chats/{CHAT}/messages?last=2", headers=UI).json()] == ["m3", "m4"]


def test_audio_returns_the_decrypted_bytes_without_caching(client):
    r = client.get(f"/whatsapp/chats/{CHAT}/messages/m2/audio", headers=UI)
    assert r.status_code == 200 and r.content == PLAIN
    assert r.headers["content-type"] == "audio/ogg" and r.headers["cache-control"] == "no-store"


def test_audio_errors(client):
    assert client.get(f"/whatsapp/chats/{CHAT}/messages/m1/audio", headers=UI).status_code == 404  # text message
    assert client.get(f"/whatsapp/chats/{CHAT}/messages/m3/audio", headers=UI).status_code == 404  # no download details
    assert client.get(f"/whatsapp/chats/{CHAT}/messages/zzz/audio", headers=UI).status_code == 404  # unknown id


def test_reading_messages_needs_the_ui_header(client):
    assert client.get(f"/whatsapp/chats/{CHAT}/messages").status_code == 403
    assert client.get(f"/whatsapp/chats/{CHAT}/messages/m2/audio").status_code == 403


def test_a_corrupt_download_is_a_502_not_a_crash():
    store = JobStore(":memory:")
    bad = lambda: httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=os.urandom(80))))  # noqa: E731
    wa = WhatsAppService(FakeProvider(), ActionStore(":memory:"), audio_client_factory=bad)
    client = TestClient(create_app(Engine(FakeGate(), FakeLLM(), store), store, whatsapp=wa))
    assert client.get(f"/whatsapp/chats/{CHAT}/messages/m2/audio", headers=UI).status_code == 502


def test_system_events_are_not_shown_and_the_limit_counts_only_what_is_shown():
    class Provider(FakeProvider):
        async def get_messages(self, chat_id, last=20):
            noise = [Message(f"n{i}", chat_id, "x", "", TS, False, "call_log") for i in range(50)]
            real = [Message("a1", chat_id, "Maria", "", TS, False, "ptt", 10, REF), Message("a2", chat_id, "Maria", "oi", TS, False)]
            return (real[:1] + noise + real[1:])[-last:]

    store = JobStore(":memory:")
    wa = WhatsAppService(Provider(), ActionStore(":memory:"))
    client = TestClient(create_app(Engine(FakeGate(), FakeLLM(), store), store, whatsapp=wa))
    items = client.get(f"/whatsapp/chats/{CHAT}/messages?last=2", headers=UI).json()
    assert [i["id"] for i in items] == ["a1", "a2"]  # the earlier voice note is not pushed out by 50 call-log entries
