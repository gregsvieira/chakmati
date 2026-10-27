from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from chakmati.agenda.ics import IcsCalendarProvider
from chakmati.agenda.models import NewEvent
from chakmati.agenda.service import ActionStore, CalendarService
from chakmati.api import create_app
from chakmati.engine import Engine
from chakmati.gate.base import GateResult, Route
from chakmati.jobs import JobStore

BRT = timezone(timedelta(hours=-3))
T0 = datetime(2026, 10, 24, 15, 0, tzinfo=BRT)
UI = {"X-LiteAgent-UI": "1"}


class Clock:
    t = 1000.0

    def __call__(self):
        return self.t


class FakeGate:
    def classify(self, text):
        return GateResult(Route.CHAT, 1.0, "fake")


class FakeLLM:
    async def chat(self, messages):
        return "x"


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def service(tmp_path, clock):
    return CalendarService(IcsCalendarProvider(str(tmp_path / "a.ics")), ActionStore(":memory:"), 3600, clock)


@pytest.fixture
def client(service):
    store = JobStore(":memory:")
    return TestClient(create_app(Engine(FakeGate(), FakeLLM(), store), store, calendar=service))


def test_events_endpoint_lists_events_as_json(client, service):
    service._provider.create_event(NewEvent("Reunião", T0, T0 + timedelta(hours=1), location="Sala 2"))
    r = client.get("/agenda/events", params={"start": "2026-10-24T00:00:00-03:00", "end": "2026-10-25T00:00:00-03:00"})
    assert r.status_code == 200
    (e,) = r.json()
    assert e["title"] == "Reunião" and e["location"] == "Sala 2" and e["all_day"] is False
    assert datetime.fromisoformat(e["start"]) == T0


def test_events_endpoint_rejects_naive_or_inverted_ranges(client):
    assert client.get("/agenda/events", params={"start": "2026-10-24T00:00:00", "end": "2026-10-25T00:00:00"}).status_code == 422
    assert client.get("/agenda/events", params={"start": "2026-10-25T00:00:00-03:00", "end": "2026-10-24T00:00:00-03:00"}).status_code == 422


def test_pending_actions_are_listed_and_hold_back_the_write(client, service):
    action = service.propose_create(NewEvent("Dentista", T0, T0 + timedelta(hours=1)))
    (item,) = client.get("/actions").json()
    assert item["id"] == action.id and item["status"] == "pending" and "Dentista" in item["summary"]
    assert service._provider.list_events(T0 - timedelta(hours=1), T0 + timedelta(hours=2)) == []  # nothing written


def test_approve_requires_the_ui_header(client, service):
    action = service.propose_create(NewEvent("Dentista", T0, T0 + timedelta(hours=1)))
    assert client.post(f"/actions/{action.id}/approve").status_code == 403
    assert client.post(f"/actions/{action.id}/reject").status_code == 403
    assert service._actions.get(action.id).status == "pending"


def test_approve_writes_the_event_and_cannot_repeat(client, service):
    action = service.propose_create(NewEvent("Dentista", T0, T0 + timedelta(hours=1)))
    r = client.post(f"/actions/{action.id}/approve", headers=UI)
    assert r.status_code == 200 and r.json()["status"] == "executed"
    assert [e.title for e in service._provider.list_events(T0 - timedelta(hours=1), T0 + timedelta(hours=2))] == ["Dentista"]
    assert client.post(f"/actions/{action.id}/approve", headers=UI).status_code == 409


def test_delete_flow_over_http(client, service):
    ev = service._provider.create_event(NewEvent("Apagar-me", T0, T0 + timedelta(hours=1)))
    action = service.propose_delete(ev)
    assert client.post(f"/actions/{action.id}/approve", headers=UI).json()["status"] == "executed"
    assert service._provider.list_events(T0 - timedelta(hours=1), T0 + timedelta(hours=2)) == []


def test_reject_unknown_and_expired(client, service, clock):
    a = service.propose_create(NewEvent("A", T0, T0 + timedelta(hours=1)))
    assert client.post(f"/actions/{a.id}/reject", headers=UI).json()["status"] == "rejected"
    assert client.post(f"/actions/{a.id}/approve", headers=UI).status_code == 409
    assert client.post("/actions/nope/approve", headers=UI).status_code == 404
    b = service.propose_create(NewEvent("B", T0, T0 + timedelta(hours=1)))
    clock.t += 3601
    assert client.post(f"/actions/{b.id}/approve", headers=UI).status_code == 410


def test_everything_is_503_when_the_calendar_is_disabled():
    store = JobStore(":memory:")
    c = TestClient(create_app(Engine(FakeGate(), FakeLLM(), store), store))
    assert c.get("/agenda/events", params={"start": "2026-10-24T00:00:00-03:00", "end": "2026-10-25T00:00:00-03:00"}).status_code == 503
    assert c.get("/actions").status_code == 503
    assert c.post("/actions/x/approve", headers=UI).status_code == 503


def test_build_app_wires_the_calendar_only_when_enabled(tmp_path):
    from chakmati.config import Settings
    from chakmati.main import build_app

    off = TestClient(build_app(Settings(db_path=":memory:")))
    assert off.get("/actions").json() == []  # the computer's own approvals (files) always exist, even with no integration
    on = TestClient(build_app(Settings(db_path=":memory:", calendar_backend="ics", calendar_ics_path=str(tmp_path / "a.ics"))))
    assert on.get("/actions").json() == []
