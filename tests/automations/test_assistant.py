import json
from datetime import datetime, timezone

import pytest

from chakmati.approvals import ActionStore
from chakmati.automations.assistant import AutomationAssistant, cron_for, parse_intent
from chakmati.automations.service import AutomationService
from chakmati.automations.store import AutomationStore
from chakmati.whatsapp.models import Chat

TS = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)
MARIA = Chat("111@lid", "Maria Silva", False, 0, TS, "5511111")
MARIA2 = Chat("222@lid", "Maria Souza", False, 0, TS)
JOAO = Chat("333@lid", "João Pereira", False, 0, TS)


class ScriptedLLM:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    async def chat(self, messages):
        self.calls.append(messages)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


class FakeWhatsApp:
    def __init__(self, chats=(MARIA, MARIA2, JOAO)):
        self._chats = list(chats)

    async def chats(self, unread_only=False, limit=50):
        return self._chats


class FakeSynth:
    def __init__(self, installed=True):
        self.store = type("S", (), {"installed": lambda self: installed})()

    def synthesize(self, text, speed="normal"):
        from .test_audio_service import sine_wav

        return sine_wav(0.3)


def make(tmp_path, reply, extra=(), installed=True, now=lambda: 1000.0):
    store, actions = AutomationStore(":memory:"), ActionStore(":memory:")
    service = AutomationService(store, actions, FakeSynth(installed), tmp_path, now=now)
    llm = ScriptedLLM(reply, *extra)
    return AutomationAssistant(llm, service, FakeWhatsApp(), now=now), llm, service, store


def intent(**kw):
    base = {"action": "create", "name": None, "when": "message", "time": None, "days": None, "event_words": None, "minutes_before": None,
            "include_groups": False, "cooldown_minutes": None, "reply_mode": "text", "reply_text": "Estou ocupado, já te respondo.", "to": None}
    return json.dumps({**base, **kw})


# ----------------------------------------------------------------------------- pieces done in code
@pytest.mark.parametrize("time, days, expected", [
    ("09:00", None, "0 9 * * *"), ("9:30", "daily", "30 9 * * *"), ("08:15", "weekdays", "15 8 * * 1-5"),
    ("10:00", "weekend", "0 10 * * 0,6"), ("18:00", [1, 3, 5], "0 18 * * 1,3,5"), ("07:05", [5], "5 7 * * 5"),
])
def test_the_cron_is_built_by_code_from_the_time_and_days(time, days, expected):
    assert cron_for(time, days) == expected


@pytest.mark.parametrize("time, days", [("25:00", None), ("9h", None), (None, None), ("09:00", [9]), ("09:00", "sometimes"), ("09:60", None)])
def test_a_bad_time_or_days_gives_nothing(time, days):
    assert cron_for(time, days) is None


def test_the_intent_is_read_from_noisy_json_and_unknown_actions_fall_back():
    assert parse_intent("claro:\n```" + intent() + "```").action == "create"
    assert parse_intent('{"action":"hack"}').action == "other" and parse_intent("no json").action == "other"


# ----------------------------------------------------------------------------- creating
async def test_creating_a_reply_to_everyone_proposes_it_and_asks_to_confirm(tmp_path):
    a, llm, service, store = make(tmp_path, intent())
    out = await a.handle("crie uma automação: sempre que eu receber mensagem no whatsapp responda: Estou ocupado, já te respondo.")
    assert "Estou ocupado, já te respondo." in out and "Confirma" in out and "[[action:" in out
    assert store.list() == []  # nothing exists until it is confirmed
    pending = service.pending_confirmation()
    assert pending is not None and pending.payload["spec"]["action"]["text"] == "Estou ocupado, já te respondo."
    assert pending.payload["spec"]["trigger"] == {"type": "whatsapp_message", "include_groups": False, "cooldown_minutes": 120}


async def test_a_voice_reply_is_recorded_and_the_person_is_told_they_can_listen(tmp_path):
    a, _, service, _ = make(tmp_path, intent(reply_mode="voice"))
    out = await a.handle("automatize responder em áudio")
    pending = service.pending_confirmation()
    assert pending.payload["voice"] is True and service.preview(pending.id) is not None
    assert "áudio" in out and "ouvir" in out.lower()


async def test_a_voice_reply_without_the_enhanced_voice_explains_what_to_turn_on(tmp_path):
    a, _, service, _ = make(tmp_path, intent(reply_mode="voice"), installed=False)
    out = await a.handle("responda em áudio")
    assert "Voz melhorada" in out and service.pending_confirmation() is None


async def test_the_reply_text_missing_asks_for_it_instead_of_guessing(tmp_path):
    a, _, service, _ = make(tmp_path, intent(reply_text=None))
    out = await a.handle("crie uma automação para responder mensagens")
    assert "responder" in out.lower() and "?" in out and service.pending_confirmation() is None


async def test_a_schedule_to_a_named_person(tmp_path):
    a, _, service, _ = make(tmp_path, intent(when="time", time="09:00", days="weekdays", to="João", reply_text="Bom dia!"))
    out = await a.handle("todo dia útil às 9h mande bom dia para o João")
    spec = service.pending_confirmation().payload["spec"]
    assert spec["trigger"] == {"type": "schedule", "cron": "0 9 * * 1-5"} and spec["action"]["to"] == {"chat_id": "333@lid", "name": "João Pereira"}
    assert "João Pereira" in out and "Confirma" in out


async def test_a_calendar_trigger(tmp_path):
    a, _, service, _ = make(tmp_path, intent(when="event", event_words="reunião", minutes_before=5, to="João", reply_text="Estou a caminho"))
    await a.handle("5 minutos antes de toda reunião avise o João que estou a caminho")
    assert service.pending_confirmation().payload["spec"]["trigger"] == {"type": "calendar_event", "title_contains": "reunião", "minutes_before": 5}


async def test_a_schedule_without_a_time_or_recipient_asks(tmp_path):
    a, _, service, _ = make(tmp_path, intent(when="time", time=None, to="João"))
    assert "horas" in (await a.handle("todo dia mande bom dia pro João")).lower() and service.pending_confirmation() is None
    a2, _, service2, _ = make(tmp_path, intent(when="time", time="09:00", to=None))
    assert "para quem" in (await a2.handle("todo dia às 9h mande bom dia")).lower() and service2.pending_confirmation() is None


async def test_an_ambiguous_name_asks_which_and_the_answer_continues_without_asking_the_model_again(tmp_path):
    a, llm, service, _ = make(tmp_path, intent(when="time", time="09:00", to="Maria", reply_text="Bom dia!"))
    out = await a.handle("todo dia às 9h mande bom dia para a Maria")
    assert "Maria Silva" in out and "Maria Souza" in out and service.pending_confirmation() is None
    assert a.awaiting_choice("Maria Souza") is True and a.awaiting_choice("quanto é 2+2") is False
    final = await a.handle("Maria Souza")
    assert service.pending_confirmation().payload["spec"]["action"]["to"]["chat_id"] == "222@lid" and "Confirma" in final
    assert len(llm.calls) == 1 and a.awaiting_choice("Maria Souza") is False


async def test_groups_are_only_included_when_asked_and_cooldown_is_respected(tmp_path):
    a, _, service, _ = make(tmp_path, intent(include_groups=True, cooldown_minutes=30))
    await a.handle("responda também nos grupos, no máximo a cada 30 minutos")
    assert service.pending_confirmation().payload["spec"]["trigger"] == {"type": "whatsapp_message", "include_groups": True, "cooldown_minutes": 30}


async def test_an_invalid_request_is_explained_not_stored(tmp_path):
    a, _, service, _ = make(tmp_path, intent(when="time", time="09:00", days="daily", to="João", reply_text="x" * 1500))
    out = await a.handle("todo dia mande um texto enorme")
    assert "Não consegui" in out and service.pending_confirmation() is None


# ----------------------------------------------------------------------------- listing and other
async def test_listing_shows_what_exists_and_says_so_when_there_is_nothing(tmp_path):
    a, _, service, store = make(tmp_path, '{"action":"list"}')
    assert "não tem nenhuma" in (await a.handle("quais automações eu tenho?")).lower()
    service.approve(service.propose_create(__import__("chakmati.automations.models", fromlist=["parse_spec"]).parse_spec(
        {"name": "Ocupado", "trigger": {"type": "whatsapp_message"}, "action": {"type": "whatsapp_text", "to": "sender", "text": "Estou ocupado"}})).id)
    out = await a.handle("quais automações eu tenho?")
    assert "Ocupado" in out and "Estou ocupado" in out and "ativa" in out.lower()


async def test_unclear_requests_get_help(tmp_path):
    a, _, _, _ = make(tmp_path, '{"action":"other"}')
    assert "automação" in (await a.handle("blá")).lower()
