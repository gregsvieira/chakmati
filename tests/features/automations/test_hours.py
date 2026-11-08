"""An automation with the hours it works: "sempre que alguém me escrever no WhatsApp entre as 22:00 e as 07:50, responda em áudio: ..."."""

from datetime import datetime

import pytest

from chakmati.features.automations.assistant import AutomationAssistant, hours_from_text, parse_intent
from chakmati.features.automations.models import SpecError, describe, in_hours, parse_spec
from chakmati.features.automations.runner import AutomationRunner
from chakmati.features.automations.service import AutomationService
from chakmati.features.automations.store import AutomationStore

NIGHT = {"from": "22:00", "to": "07:50"}


def spec(hours=None, **trigger):
    t = {"type": "whatsapp_message", **trigger}
    if hours is not None:
        t["hours"] = hours
    return parse_spec({"name": "x", "trigger": t, "action": {"type": "whatsapp_text", "to": "sender", "text": "Estou ocupado"}})


# --- the window ------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("hour,minute,inside", [
    (21, 59, False), (22, 0, True), (23, 59, True), (0, 0, True), (3, 30, True), (7, 49, True), (7, 50, False), (12, 0, False),
])
def test_a_window_across_midnight_includes_its_start_and_excludes_its_end(hour, minute, inside):
    assert in_hours(NIGHT, datetime(2026, 11, 8, hour, minute)) is inside


@pytest.mark.parametrize("hour,minute,inside", [(8, 59, False), (9, 0, True), (16, 59, True), (17, 0, False), (23, 0, False)])
def test_a_window_inside_one_day(hour, minute, inside):
    assert in_hours({"from": "09:00", "to": "17:00"}, datetime(2026, 11, 8, hour, minute)) is inside


def test_without_hours_it_is_always_on():
    assert in_hours(None, datetime(2026, 11, 8, 3, 0)) and in_hours({}, datetime(2026, 11, 8, 15, 0))


# --- the spec ------------------------------------------------------------------------------------------------------------------------------------
def test_the_hours_are_kept_in_the_trigger_and_said_in_the_sentence_the_person_confirms():
    s = spec(NIGHT)
    assert s.trigger["hours"] == NIGHT
    assert "entre as 22:00 e as 07:50" in describe(s)
    assert "hours" not in spec().trigger and "entre as" not in describe(spec())


@pytest.mark.parametrize("hours", [{"from": "22:00"}, {"from": "25:00", "to": "07:00"}, {"from": "22:00", "to": "7:00"}, {"from": "22:00", "to": "22:00"}, "noite", {"from": 22, "to": 7}, []])
def test_bad_hours_are_refused(hours):
    with pytest.raises(SpecError):
        spec(hours)


# --- the words ---------------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("Crie uma automação: sempre que alguém me escrever no WhatsApp entre as 22:00 e as 07:50, responda em áudio: oi", NIGHT),
    ("sempre que me escreverem das 22h às 7h50 responda: oi", NIGHT),
    ("de 18:00 até 08:30 responda: oi", {"from": "18:00", "to": "08:30"}),
    ("entre 9 horas e 17 horas responda: oi", {"from": "09:00", "to": "17:00"}),
    ("sempre que me escreverem responda: oi", None),
    ("todo dia às 9h mande bom dia para o João", None),
    ("sempre que me escreverem responda: estou ocupado das 9h às 17h", None),     # that is the reply, not the hours
    ("sempre que me escreverem responda: preço de 5 a 10 reais", None),
])
def test_the_hours_are_read_from_the_persons_words_and_never_from_the_reply(text, expected):
    assert hours_from_text(text) == expected


@pytest.mark.parametrize("text", ["entre as 25:00 e as 07:00 responda: oi", "das 22:00 às 22:00 responda: oi"])
def test_hours_that_do_not_exist_are_said_not_ignored(text):
    with pytest.raises(ValueError):
        hours_from_text(text)


def test_the_models_hours_are_used_only_when_they_are_valid():
    ok = parse_intent('{"action":"create","when":"message","hours_from":"22:00","hours_to":"07:50","reply_text":"oi"}')
    assert ok.hours == NIGHT
    for bad in ('"hours_from":"22h","hours_to":"7h"', '"hours_from":"22:00","hours_to":"22:00"', '"hours_from":"22:00"'):
        assert parse_intent('{"action":"create","when":"message",' + bad + ',"reply_text":"oi"}').hours is None


# --- the assistant ---------------------------------------------------------------------------------------------------------------------------------
class LLM:
    def __init__(self, reply):
        self.reply = reply

    async def chat(self, messages, schema=None):
        return self.reply


class WA:
    async def chats(self, limit=0):
        return []

    async def media_supported(self):
        return True


def assistant(reply, tmp_path):
    store = AutomationStore(":memory:")
    from chakmati.shared.approvals import ActionStore
    service = AutomationService(store, ActionStore(":memory:"), WA(), voice_dir=str(tmp_path))
    return AutomationAssistant(LLM(reply), service, WA()), store


async def test_the_person_words_win_over_a_model_that_missed_the_hours(tmp_path):
    a, _ = assistant('{"action":"create","when":"message","reply_mode":"text","reply_text":"Estou ocupado"}', tmp_path)
    out = await a.handle("Crie uma automação: sempre que alguém me escrever no WhatsApp entre as 22:00 e as 07:50, responda: Estou ocupado")
    assert "entre as 22:00 e as 07:50" in out and "Confirma?" in out


async def test_without_hours_nothing_is_added_and_bad_hours_are_a_sentence(tmp_path):
    a, _ = assistant('{"action":"create","when":"message","reply_mode":"text","reply_text":"Estou ocupado"}', tmp_path)
    assert "entre as" not in await a.handle("sempre que alguém me escrever no WhatsApp responda: Estou ocupado")
    assert (await a.handle("sempre que me escreverem entre as 25:00 e as 07:00 responda: oi")).startswith("Não entendi o horário")


# --- the runner ---------------------------------------------------------------------------------------------------------------------------------
class Chat:
    def __init__(self, id, name="Maria", is_group=False):
        self.id, self.name, self.is_group = id, name, is_group


class Sender:
    def __init__(self):
        self.sent = []

    async def send_automated(self, chat_id, chat_name, text=None, audio=None, mime=None, source=""):
        self.sent.append((chat_id, text))


def timestamp(hour, minute=0):
    return datetime(2026, 11, 8, hour, minute).timestamp()


async def run_at(hours, hour, minute=0):
    store = AutomationStore(":memory:")
    wa = Sender()
    store.create(spec(hours), 0.0)
    runner = AutomationRunner(store, wa, now=lambda: timestamp(hour, minute))
    await runner.on_whatsapp_messages([(Chat("5511999990000@c.us"), 1)])
    return wa.sent, store


async def test_inside_its_hours_it_answers_and_outside_it_does_nothing_and_keeps_its_cooldown():
    sent, _ = await run_at(NIGHT, 23, 30)
    assert len(sent) == 1
    sent, store = await run_at(NIGHT, 12, 0)
    assert sent == []
    assert all(store.last_run(a.id, "5511999990000@c.us") is None for a in store.list())      # outside the hours no cooldown was spent


async def test_without_hours_it_answers_at_any_time():
    assert len((await run_at(None, 3, 0))[0]) == 1 and len((await run_at(None, 15, 0))[0]) == 1


async def test_the_edge_of_the_window():
    assert len((await run_at(NIGHT, 7, 49))[0]) == 1
    assert (await run_at(NIGHT, 7, 50))[0] == []
