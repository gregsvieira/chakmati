from datetime import datetime, timezone

import pytest

from liteagent.automations.cron import CronError, cron_matches, describe_cron, fires_per_day, validate_cron
from liteagent.automations.models import SpecError, describe, parse_spec
from liteagent.automations.store import AutomationStore

SAT_0900 = datetime(2026, 10, 24, 9, 0, tzinfo=timezone.utc)  # a Saturday
MON_0900 = datetime(2026, 10, 26, 9, 0, tzinfo=timezone.utc)


# ----------------------------------------------------------------------------- cron
@pytest.mark.parametrize("expr, when, expected", [
    ("0 9 * * *", SAT_0900, True),
    ("0 9 * * *", SAT_0900.replace(minute=1), False),
    ("0 9 * * 1-5", SAT_0900, False),      # Monday to Friday: not on a Saturday
    ("0 9 * * 1-5", MON_0900, True),
    ("0 9 * * 6", SAT_0900, True),         # 6 = Saturday
    ("0 9 * * 0,6", SAT_0900, True),       # weekend
    ("0 9 * * 7", MON_0900.replace(day=25), True),  # 7 is Sunday too
    ("*/15 * * * *", SAT_0900.replace(minute=45), True),
    ("*/15 * * * *", SAT_0900.replace(minute=40), False),
    ("30 8-10 * * *", SAT_0900.replace(hour=10, minute=30), True),
    ("0 9 24 10 *", SAT_0900, True),
    ("0 9 25 10 *", SAT_0900, False),
])
def test_cron_matches(expr, when, expected):
    assert cron_matches(expr, when) is expected


@pytest.mark.parametrize("bad", ["", "* * * *", "60 * * * *", "* 24 * * *", "* * 32 * *", "* * * 13 *", "* * * * 8", "a b c d e", "*/0 * * * *", "5-1 * * * *"])
def test_bad_cron_is_refused(bad):
    with pytest.raises(CronError):
        validate_cron(bad)


def test_fires_per_day_counts_the_matching_minutes():
    assert fires_per_day("0 9 * * *") == 1
    assert fires_per_day("0 */2 * * *") == 12
    assert fires_per_day("* * * * *") == 1440


def test_cron_in_words():
    assert describe_cron("0 9 * * *") == "todo dia às 09:00"
    assert describe_cron("30 8 * * 1-5") == "de segunda a sexta às 08:30"
    assert describe_cron("0 18 * * 5") == "toda sexta-feira às 18:00"
    assert describe_cron("0 9 * * 0,6") == "aos sábados e domingos às 09:00"
    assert describe_cron("*/15 * * * *") == "no horário agendado (*/15 * * * *)"  # anything unusual is shown as written


# ----------------------------------------------------------------------------- the specification
def base(trigger, action):
    return {"name": "Teste", "trigger": trigger, "action": action}


def test_a_message_trigger_with_a_text_reply_is_valid_and_gets_safe_defaults():
    spec = parse_spec(base({"type": "whatsapp_message"}, {"type": "whatsapp_text", "to": "sender", "text": "  Estou ocupado, já te respondo.  "}))
    assert spec.trigger == {"type": "whatsapp_message", "include_groups": False, "cooldown_minutes": 120}
    assert spec.action == {"type": "whatsapp_text", "to": "sender", "text": "Estou ocupado, já te respondo."}


def test_replying_to_the_sender_only_makes_sense_for_a_message_trigger():
    with pytest.raises(SpecError, match="sender"):
        parse_spec(base({"type": "schedule", "cron": "0 9 * * *"}, {"type": "whatsapp_text", "to": "sender", "text": "oi"}))


def test_a_schedule_needs_a_valid_cron_and_a_fixed_recipient():
    chat = {"chat_id": "123@lid", "name": "Maria"}
    spec = parse_spec(base({"type": "schedule", "cron": "0 9 * * 1-5"}, {"type": "whatsapp_text", "to": chat, "text": "Bom dia!"}))
    assert spec.trigger["cron"] == "0 9 * * 1-5" and spec.action["to"] == chat
    with pytest.raises(SpecError):
        parse_spec(base({"type": "schedule", "cron": "nope"}, {"type": "whatsapp_text", "to": chat, "text": "oi"}))


def test_a_schedule_cannot_fire_more_than_24_times_a_day():
    chat = {"chat_id": "123@lid", "name": "Maria"}
    with pytest.raises(SpecError, match="24"):
        parse_spec(base({"type": "schedule", "cron": "*/5 * * * *"}, {"type": "whatsapp_text", "to": chat, "text": "oi"}))


def test_calendar_trigger():
    chat = {"chat_id": "123@lid", "name": "Maria"}
    spec = parse_spec(base({"type": "calendar_event", "title_contains": " Reunião ", "minutes_before": 5}, {"type": "whatsapp_text", "to": chat, "text": "Estou a caminho"}))
    assert spec.trigger == {"type": "calendar_event", "title_contains": "Reunião", "minutes_before": 5}
    with pytest.raises(SpecError):
        parse_spec(base({"type": "calendar_event", "title_contains": "", "minutes_before": 5}, {"type": "whatsapp_text", "to": chat, "text": "oi"}))
    with pytest.raises(SpecError):
        parse_spec(base({"type": "calendar_event", "title_contains": "x", "minutes_before": 999}, {"type": "whatsapp_text", "to": chat, "text": "oi"}))


@pytest.mark.parametrize("trigger, action", [
    ({"type": "teleport"}, {"type": "whatsapp_text", "to": "sender", "text": "oi"}),
    ({"type": "whatsapp_message"}, {"type": "format_disk", "to": "sender", "text": "oi"}),
    ({"type": "whatsapp_message"}, {"type": "whatsapp_text", "to": "sender", "text": ""}),
    ({"type": "whatsapp_message"}, {"type": "whatsapp_text", "to": "sender", "text": "x" * 1001}),
    ({"type": "whatsapp_message"}, {"type": "whatsapp_text", "to": "sender", "text": "bom\x00dia"}),
    ({"type": "whatsapp_message", "cooldown_minutes": 0}, {"type": "whatsapp_text", "to": "sender", "text": "oi"}),
    ({"type": "whatsapp_message", "cooldown_minutes": 99999}, {"type": "whatsapp_text", "to": "sender", "text": "oi"}),
    ({"type": "whatsapp_message"}, {"type": "whatsapp_text", "to": {"chat_id": "bad id", "name": "x"}, "text": "oi"}),
])
def test_invalid_specifications_are_refused(trigger, action):
    with pytest.raises(SpecError):
        parse_spec(base(trigger, action))


def test_the_name_is_trimmed_and_limited():
    with pytest.raises(SpecError):
        parse_spec({"name": "x" * 61, "trigger": {"type": "whatsapp_message"}, "action": {"type": "whatsapp_text", "to": "sender", "text": "oi"}})
    spec = parse_spec({"name": "  ", "trigger": {"type": "whatsapp_message"}, "action": {"type": "whatsapp_text", "to": "sender", "text": "oi"}})
    assert spec.name  # a default name is made up


def test_the_description_says_what_will_happen_in_plain_portuguese():
    spec = parse_spec(base({"type": "whatsapp_message"}, {"type": "whatsapp_voice", "to": "sender", "text": "Estou ocupado"}))
    text = describe(spec)
    assert "escrever" in text and "áudio" in text and "Estou ocupado" in text and "2 horas" in text and "grupos" in text.lower()
    chat = {"chat_id": "123@lid", "name": "Maria"}
    cal = describe(parse_spec(base({"type": "calendar_event", "title_contains": "reunião", "minutes_before": 5}, {"type": "whatsapp_text", "to": chat, "text": "Já vou"})))
    assert "5 min antes" in cal and "reunião" in cal and "Maria" in cal


# ----------------------------------------------------------------------------- the store
def test_store_creates_lists_toggles_and_deletes():
    store = AutomationStore(":memory:")
    spec = parse_spec(base({"type": "whatsapp_message"}, {"type": "whatsapp_text", "to": "sender", "text": "oi"}))
    auto = store.create(spec, now=1000.0)
    assert auto.enabled and auto.runs == 0 and auto.id
    assert [a.id for a in store.list()] == [auto.id]
    store.set_enabled(auto.id, False)
    assert store.get(auto.id).enabled is False and store.list(enabled_only=True) == []
    assert store.get(auto.id).spec.action["text"] == "oi"
    assert store.delete(auto.id) is True and store.list() == [] and store.delete(auto.id) is False


def test_store_records_runs_and_remembers_the_last_run_per_key():
    store = AutomationStore(":memory:")
    spec = parse_spec(base({"type": "whatsapp_message"}, {"type": "whatsapp_text", "to": "sender", "text": "oi"}))
    auto = store.create(spec, now=1000.0)
    assert store.last_run(auto.id, "chat-1") is None
    store.record_run(auto.id, "chat-1", "ok", now=2000.0)
    store.record_run(auto.id, "chat-2", "ok", now=2500.0)
    assert store.last_run(auto.id, "chat-1") == 2000.0 and store.last_run(auto.id, "chat-2") == 2500.0
    assert store.get(auto.id).runs == 2 and store.get(auto.id).last_run_at == 2500.0
    assert [r["key"] for r in store.recent_runs(auto.id)] == ["chat-2", "chat-1"]
    store.delete(auto.id)
    assert store.recent_runs(auto.id) == []
