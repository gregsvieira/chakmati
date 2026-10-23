import pytest

from liteagent.agenda import factory
from liteagent.agenda.factory import LazyProvider, build_calendar
from liteagent.agenda.ics import IcsCalendarProvider
from liteagent.config import Settings


def test_off_builds_nothing():
    assert build_calendar(Settings()) is None


def test_ics_backend_uses_the_configured_file(tmp_path):
    service = build_calendar(Settings(calendar_backend="ics", calendar_ics_path=str(tmp_path / "x.ics"), db_path=":memory:"))
    assert isinstance(service._provider, IcsCalendarProvider)


def test_auto_falls_back_to_ics_off_macos(tmp_path, monkeypatch):
    monkeypatch.setattr(factory.sys, "platform", "linux")
    service = build_calendar(Settings(calendar_backend="auto", calendar_ics_path=str(tmp_path / "x.ics"), db_path=":memory:"))
    assert isinstance(service._provider, IcsCalendarProvider)


def test_auto_on_macos_is_lazy_and_does_not_ask_for_permission_at_startup(monkeypatch):
    monkeypatch.setattr(factory.sys, "platform", "darwin")
    built = []
    monkeypatch.setattr(factory, "_make_mac", lambda name: built.append(name) or object())
    service = build_calendar(Settings(calendar_backend="auto", calendar_name="Trabalho", db_path=":memory:"))
    assert isinstance(service._provider, LazyProvider) and built == []  # nothing constructed yet


def test_unknown_backend_is_an_error():
    with pytest.raises(ValueError, match="calendar_backend"):
        build_calendar(Settings(calendar_backend="outlook", db_path=":memory:"))


def test_lazy_provider_builds_on_first_use_and_retries_after_a_failure():
    attempts = []

    class Real:
        name = "real"

        def list_events(self, start, end):
            return ["ok"]

    def make():
        attempts.append(1)
        if len(attempts) == 1:
            raise PermissionError("not yet")
        return Real()

    lazy = LazyProvider(make, "real")
    assert attempts == []
    with pytest.raises(PermissionError):
        lazy.list_events(None, None)
    assert lazy.list_events(None, None) == ["ok"] and len(attempts) == 2
    lazy.list_events(None, None)
    assert len(attempts) == 2  # built once after it worked
