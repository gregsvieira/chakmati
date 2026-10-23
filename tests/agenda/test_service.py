from datetime import datetime, timedelta, timezone

import pytest

from liteagent.agenda.models import CalendarEvent, NewEvent
from liteagent.agenda.service import (
    ActionExpired,
    ActionNotPending,
    ActionStore,
    CalendarService,
)

UTC = timezone.utc
T0 = datetime(2026, 10, 24, 15, 0, tzinfo=UTC)


class FakeProvider:
    name = "fake"

    def __init__(self):
        self.events: list[CalendarEvent] = []
        self.created: list[NewEvent] = []
        self.deleted: list[str] = []
        self.fail = False

    def list_events(self, start, end):
        return [e for e in self.events if e.start < end and e.end > start]

    def create_event(self, new):
        if self.fail:
            raise RuntimeError("calendar is locked")
        self.created.append(new)
        ev = CalendarEvent(f"id{len(self.created)}", new.title, new.start, new.end, new.all_day, new.location, new.notes)
        self.events.append(ev)
        return ev

    def delete_event(self, event_id):
        if self.fail:
            raise RuntimeError("calendar is locked")
        self.deleted.append(event_id)
        self.events = [e for e in self.events if e.id != event_id]


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def provider():
    return FakeProvider()


@pytest.fixture
def service(provider, clock):
    return CalendarService(provider, ActionStore(":memory:"), ttl_seconds=3600, now=clock)


NEW = NewEvent("Reunião", T0, T0 + timedelta(hours=1), location="Sala 2")


def test_proposing_never_touches_the_calendar(service, provider):
    action = service.propose_create(NEW)
    assert action.status == "pending" and action.kind == "calendar.create"
    assert "Reunião" in action.summary and "15:00" in action.summary
    assert provider.created == [] and provider.deleted == []
    assert [a.id for a in service.pending()] == [action.id]


def test_approve_executes_exactly_once(service, provider):
    action = service.propose_create(NEW)
    done = service.approve(action.id)
    assert done.status == "executed" and "id1" in done.result
    assert provider.created == [NEW]
    with pytest.raises(ActionNotPending):
        service.approve(action.id)
    assert len(provider.created) == 1 and service.pending() == []


def test_reject_prevents_execution(service, provider):
    action = service.propose_create(NEW)
    assert service.reject(action.id).status == "rejected"
    with pytest.raises(ActionNotPending):
        service.approve(action.id)
    assert provider.created == []


def test_expired_actions_cannot_be_approved(service, provider, clock):
    action = service.propose_create(NEW)
    clock.t += 3601
    with pytest.raises(ActionExpired):
        service.approve(action.id)
    assert provider.created == [] and service.pending() == []


def test_unknown_action_raises_keyerror(service):
    with pytest.raises(KeyError):
        service.approve("nope")
    with pytest.raises(KeyError):
        service.reject("nope")


def test_provider_failure_is_recorded_not_raised(service, provider):
    provider.fail = True
    action = service.propose_create(NEW)
    done = service.approve(action.id)
    assert done.status == "failed" and "calendar is locked" in done.error
    with pytest.raises(ActionNotPending):
        service.approve(action.id)  # a failed action is not retried silently


def test_propose_delete_then_approve(service, provider):
    ev = CalendarEvent("abc", "Dentista", T0, T0 + timedelta(hours=1))
    provider.events.append(ev)
    action = service.propose_delete(ev)
    assert action.kind == "calendar.delete" and "Dentista" in action.summary and provider.deleted == []
    service.approve(action.id)
    assert provider.deleted == ["abc"]


def test_events_are_read_directly_from_the_provider(service, provider):
    provider.events.append(CalendarEvent("a", "A", T0, T0 + timedelta(hours=1)))
    assert [e.title for e in service.events(T0 - timedelta(hours=1), T0 + timedelta(hours=2))] == ["A"]


def test_payload_round_trips_all_fields(service, provider):
    full = NewEvent("Dia livre", T0.replace(hour=0), T0.replace(hour=0) + timedelta(days=1), all_day=True,
                    location="Casa", notes="n", calendar="Pessoal")
    service.approve(service.propose_create(full).id)
    assert provider.created == [full]
