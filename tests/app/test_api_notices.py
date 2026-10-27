import asyncio
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from chakmati.features.agenda.ics import IcsCalendarProvider
from chakmati.features.agenda.models import NewEvent
from chakmati.features.agenda.service import CalendarService
from chakmati.app.api import create_app
from chakmati.shared.approvals import ActionStore
from chakmati.shared.config import Settings
from chakmati.app.engine import Engine
from chakmati.shared.gate.base import GateResult, Route
from chakmati.shared.jobs import JobStore
from chakmati.main import build_app
from chakmati.shared.notices import NoticeBoard, Notifier
from chakmati.features.whatsapp.models import Chat, Status
from chakmati.features.whatsapp.openwa import WhatsAppError
from chakmati.features.whatsapp.service import WhatsAppService

TS = datetime(2026, 10, 23, 10, 0, tzinfo=timezone.utc)


class FakeGate:
    def classify(self, text):
        return GateResult(Route.CHAT, 1.0, "fake")


class FakeLLM:
    async def chat(self, messages):
        return "x"


class FakeProvider:
    def __init__(self):
        self.connected, self.error = True, None

    async def status(self):
        if self.error:
            raise self.error
        return Status(self.connected, "READY" if self.connected else "AUTHENTICATING")

    async def list_chats(self, unread_only=False, limit=50):
        if self.error:
            raise self.error
        chats = [Chat("1@lid", "Maria Victoria", False, 2, TS), Chat("2@g.us", "Família", True, 5, TS), Chat("3@lid", "Ana", False, 0, TS)]
        return [c for c in chats if c.unread > 0 or not unread_only]

    async def get_messages(self, chat_id, last=20):
        return []

    async def send_text(self, chat_id, text):
        return "id"


def make(tmp_path, with_whatsapp=True, with_calendar=True, board=None):
    store, actions = JobStore(":memory:"), ActionStore(":memory:")
    provider = FakeProvider()
    wa = WhatsAppService(provider, actions, min_interval=0) if with_whatsapp else None
    cal = CalendarService(IcsCalendarProvider(str(tmp_path / "a.ics")), actions) if with_calendar else None
    board = board or NoticeBoard()
    app = create_app(Engine(FakeGate(), FakeLLM(), store), store, calendar=cal, whatsapp=wa, board=board)
    return TestClient(app), board, wa, cal, provider


def test_notices_returns_what_is_newer_than_the_cursor(tmp_path):
    client, board, *_ = make(tmp_path)
    board.add("whatsapp", "Você recebeu uma nova mensagem de Maria", "Você recebeu uma nova mensagem no WhatsApp", "1@lid")
    board.add("system", "ok", "ok")
    body = client.get("/notices", params={"after": 0}).json()
    assert body["last_id"] == 2 and [n["id"] for n in body["notices"]] == [1, 2]
    first = body["notices"][0]
    assert set(first) == {"id", "kind", "text", "masked", "ts", "key"} and first["kind"] == "whatsapp"
    assert [n["id"] for n in client.get("/notices", params={"after": 1}).json()["notices"]] == [2]
    assert client.get("/notices", params={"after": 2}).json() == {"notices": [], "last_id": 2}


def test_notices_can_wait_for_a_new_one_and_gives_up_after_the_timeout(tmp_path):
    client, board, *_ = make(tmp_path)
    started = time.perf_counter()
    assert client.get("/notices", params={"after": 0, "wait": 0.2}).json()["notices"] == []
    assert 0.15 < time.perf_counter() - started < 2.0
    assert client.get("/notices", params={"after": 0, "wait": 999}).status_code == 422  # wait is capped


def test_overview_summarises_whatsapp_calendar_and_pending_actions(tmp_path):
    client, board, wa, cal, _ = make(tmp_path)
    now = datetime.now().astimezone()
    cal._provider.create_event(NewEvent("Dentista", now.replace(hour=15, minute=0, second=0, microsecond=0),
                                        now.replace(hour=16, minute=0, second=0, microsecond=0)))
    wa.propose_send(Chat("1@lid", "Maria Victoria", False, 0, TS), "oi")
    board.add("system", "x", "x")
    o = client.get("/overview").json()
    assert o["whatsapp"]["enabled"] and o["whatsapp"]["connected"] and o["whatsapp"]["state"] == "READY"
    assert [(c["name"], c["unread"], c["is_group"]) for c in o["whatsapp"]["unread"]] == [("Maria Victoria", 2, False), ("Família", 5, True)]
    assert o["calendar"]["enabled"] and [e["title"] for e in o["calendar"]["today"]] == ["Dentista"]
    assert [p["kind"] for p in o["pending"]] == ["whatsapp.send"] and o["last_notice_id"] == 1


def test_overview_reports_disabled_integrations_and_failures_per_section(tmp_path):
    client, *_ = make(tmp_path, with_whatsapp=False, with_calendar=False)
    o = client.get("/overview").json()
    assert o["whatsapp"] == {"enabled": False} and o["calendar"] == {"enabled": False} and o["pending"] == []

    client, _, _, _, provider = make(tmp_path)
    provider.error = WhatsAppError("OpenWA unreachable")
    o = client.get("/overview").json()
    assert o["whatsapp"]["enabled"] and "unreachable" in o["whatsapp"]["error"]
    assert o["calendar"]["enabled"] and "error" not in o["calendar"]  # one broken section does not hide the others


def test_the_notifier_runs_with_the_app_and_stops_with_it(tmp_path):
    polled = []

    class W:
        interval = 0.01

        async def poll_once(self):
            polled.append(1)

    store = JobStore(":memory:")
    board = NoticeBoard()
    app = create_app(Engine(FakeGate(), FakeLLM(), store), store, board=board, notifier=Notifier([W()]))
    with TestClient(app):
        for _ in range(100):
            if len(polled) >= 3:
                break
            time.sleep(0.02)
    assert len(polled) >= 3
    after = len(polled)
    time.sleep(0.1)
    assert len(polled) == after


def test_build_app_starts_the_watchers_that_match_the_enabled_integrations(tmp_path):
    from chakmati.features.agenda.watcher import CalendarWatcher
    from chakmati.features.automations.ticker import AutomationTicker
    from chakmati.features.whatsapp.watcher import WhatsAppWatcher
    from chakmati.shared.notices import ApprovalWatcher

    app = build_app(Settings(db_path=":memory:", calendar_backend="ics", calendar_ics_path=str(tmp_path / "a.ics"),
                             whatsapp_backend="openwa", openwa_url="http://127.0.0.1:1"))
    kinds = {type(w) for w in app.state.notifier._watchers}
    assert kinds == {WhatsAppWatcher, CalendarWatcher, ApprovalWatcher, AutomationTicker}
    off = build_app(Settings(db_path=":memory:"))
    assert off.state.notifier is None
    disabled = build_app(Settings(db_path=":memory:", calendar_backend="ics", calendar_ics_path=str(tmp_path / "b.ics"), notices_enabled=False))
    assert disabled.state.notifier is None


def test_a_cursor_from_before_an_engine_restart_does_not_hide_new_notices(tmp_path):
    client, board, *_ = make(tmp_path)  # fresh engine: ids restart from 1
    board.add("system", "primeiro depois do reinício", "m")
    body = client.get("/notices", params={"after": 57}).json()  # the app still remembers id 57 from the old run
    assert [n["text"] for n in body["notices"]] == ["primeiro depois do reinício"]
    assert body["last_id"] == 1
