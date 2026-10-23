from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from liteagent.agenda.ics import IcsCalendarProvider
from liteagent.agenda.models import NewEvent
from liteagent.agenda.service import CalendarService
from liteagent.api import create_app
from liteagent.approvals import ActionStore
from liteagent.engine import Engine
from liteagent.gate.base import GateResult, Route
from liteagent.jobs import JobStore
from liteagent.whatsapp.models import Chat, Status
from liteagent.whatsapp.service import WhatsAppService

TS = datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc)
MARIA = Chat("205123@lid", "Maria Silva", False, 2, TS, "5511999990000")
JOAO = Chat("999@lid", "João", False, 0, TS)
UI = {"X-LiteAgent-UI": "1"}


class FakeGate:
    def classify(self, text):
        return GateResult(Route.CHAT, 1.0, "fake")


class FakeLLM:
    async def chat(self, messages):
        return "x"


class FakeProvider:
    def __init__(self):
        self.sent, self.connected, self.fail = [], True, False

    async def status(self):
        return Status(self.connected, "READY" if self.connected else "AUTHENTICATING")

    async def list_chats(self, unread_only=False, limit=50):
        return [c for c in (MARIA, JOAO) if (c.unread > 0 or not unread_only)]

    async def get_messages(self, chat_id, last=20):
        return []

    async def send_text(self, chat_id, text):
        if self.fail:
            raise RuntimeError("down")
        self.sent.append((chat_id, text))
        return "id1"


@pytest.fixture
def parts(tmp_path):
    actions = ActionStore(":memory:")
    provider = FakeProvider()
    wa = WhatsAppService(provider, actions, max_sends_per_hour=1, min_interval=0)
    cal = CalendarService(IcsCalendarProvider(str(tmp_path / "a.ics")), actions)
    store = JobStore(":memory:")
    client = TestClient(create_app(Engine(FakeGate(), FakeLLM(), store), store, calendar=cal, whatsapp=wa))
    return client, wa, cal, provider


def test_one_inbox_lists_pending_actions_from_both_integrations(parts):
    client, wa, cal, _ = parts
    a = wa.propose_send(MARIA, "oi")
    t0 = datetime(2026, 10, 24, 15, 0, tzinfo=timezone(timedelta(hours=-3)))
    b = cal.propose_create(NewEvent("Dentista", t0, t0 + timedelta(hours=1)))
    items = {i["id"]: i for i in client.get("/actions").json()}
    assert set(items) == {a.id, b.id}
    assert items[a.id]["kind"] == "whatsapp.send" and items[b.id]["kind"] == "calendar.create"
    assert "Maria Silva" in items[a.id]["summary"]


def test_whatsapp_send_needs_the_ui_header_and_then_sends_once(parts):
    client, wa, _, provider = parts
    a = wa.propose_send(MARIA, "Olá, Maria!")
    assert client.post(f"/actions/{a.id}/approve").status_code == 403 and provider.sent == []
    r = client.post(f"/actions/{a.id}/approve", headers=UI)
    assert r.status_code == 200 and r.json()["status"] == "executed" and provider.sent == [("205123@lid", "Olá, Maria!")]
    assert client.post(f"/actions/{a.id}/approve", headers=UI).status_code == 409 and len(provider.sent) == 1


def test_calendar_actions_still_work_through_the_same_endpoint(parts):
    client, _, cal, _ = parts
    t0 = datetime(2026, 10, 24, 15, 0, tzinfo=timezone(timedelta(hours=-3)))
    b = cal.propose_create(NewEvent("Dentista", t0, t0 + timedelta(hours=1)))
    assert client.post(f"/actions/{b.id}/approve", headers=UI).json()["status"] == "executed"


def test_reject_does_not_send(parts):
    client, wa, _, provider = parts
    a = wa.propose_send(MARIA, "oi")
    assert client.post(f"/actions/{a.id}/reject", headers=UI).json()["status"] == "rejected"
    assert provider.sent == [] and client.post("/actions/nope/approve", headers=UI).status_code == 404


def test_rate_limit_returns_429_and_keeps_the_proposal_pending(parts):
    client, wa, _, provider = parts
    first, second = wa.propose_send(MARIA, "um"), wa.propose_send(MARIA, "dois")
    assert client.post(f"/actions/{first.id}/approve", headers=UI).status_code == 200
    r = client.post(f"/actions/{second.id}/approve", headers=UI)
    assert r.status_code == 429 and "limite" in r.json()["detail"]
    assert [a["id"] for a in client.get("/actions").json()] == [second.id] and len(provider.sent) == 1


def test_provider_failure_is_reported_as_a_failed_action(parts):
    client, wa, _, provider = parts
    provider.fail = True
    r = client.post(f"/actions/{wa.propose_send(MARIA, 'oi').id}/approve", headers=UI)
    assert r.status_code == 200 and r.json()["status"] == "failed" and "down" in r.json()["error"]


def test_status_and_chats_endpoints(parts):
    client, _, _, provider = parts
    assert client.get("/whatsapp/status").json() == {"connected": True, "state": "READY"}
    chats = client.get("/whatsapp/chats", params={"unread": "true"}).json()
    assert [c["name"] for c in chats] == ["Maria Silva"] and chats[0]["unread"] == 2 and chats[0]["id"] == "205123@lid"
    assert [c["name"] for c in client.get("/whatsapp/chats").json()] == ["Maria Silva", "João"]
    provider.connected = False
    assert client.get("/whatsapp/status").json()["connected"] is False


def test_everything_is_503_when_whatsapp_is_disabled(tmp_path):
    store = JobStore(":memory:")
    c = TestClient(create_app(Engine(FakeGate(), FakeLLM(), store), store))
    assert c.get("/whatsapp/status").status_code == 503 and c.get("/whatsapp/chats").status_code == 503


def test_build_app_wires_whatsapp_only_when_enabled(tmp_path):
    from liteagent.config import Settings
    from liteagent.main import build_app

    off = TestClient(build_app(Settings(db_path=":memory:")))
    assert off.get("/whatsapp/status").status_code == 503
    on = TestClient(build_app(Settings(db_path=":memory:", whatsapp_backend="openwa", openwa_url="http://127.0.0.1:1",
                                       openwa_api_key_file=str(tmp_path / "none"))))
    assert on.get("/actions").json() == []  # the inbox exists; OpenWA being down only matters when it is used
