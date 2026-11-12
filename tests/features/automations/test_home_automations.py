"""Automations that do things in the house: "todo dia às 7h ligue a luz do quarto e abra a cortina", "de segunda a sexta às 6h30 toque Raul Seixas na Alexa"."""

from datetime import datetime

import pytest

from chakmati.features.automations.assistant import AutomationAssistant, days_from_text, parse_intent, time_from_text
from chakmati.features.automations.models import SpecError, describe, parse_spec
from chakmati.features.automations.runner import AutomationRunner
from chakmati.features.automations.service import AutomationService
from chakmati.features.automations.store import AutomationStore
from chakmati.features.home.models import Entity, HomeError
from chakmati.features.home.service import HomeService
from chakmati.shared.approvals import ActionStore

LUZ = Entity("light.quarto", "Luz do quarto", "light", "off")
CORTINA = Entity("cover.cortina_quarto", "Cortina do quarto", "cover", "closed", "curtain")
GARAGEM = Entity("cover.garagem", "Portão da garagem", "cover", "closed", "garage")
PORTA = Entity("lock.porta", "Porta da frente", "lock", "locked")
ECHO = Entity("media_player.echo", "Echo Dot da Maria", "media_player", "idle")


def dev(action, entity, value=None):
    step = {"kind": "device", "action": action, "entity": {"id": entity.id, "name": entity.name, "device_class": entity.device_class}}
    if value is not None:
        step["value"] = value
    return step


MUSIC = {"kind": "music", "entity": {"id": ECHO.id, "name": ECHO.name}, "query": "Raul Seixas"}


def spec(steps, trigger=None):
    return parse_spec({"trigger": trigger or {"type": "schedule", "cron": "0 7 * * *"}, "action": {"type": "home_steps", "steps": steps}})


# --- the spec ------------------------------------------------------------------------------------------------------------------------------------
def test_the_sentence_the_person_confirms_says_every_step():
    s = spec([dev("on", LUZ), dev("open", CORTINA), MUSIC])
    assert describe(s) == "Todo dia às 07:00, ligar Luz do quarto e abrir Cortina do quarto e pedir à Echo Dot da Maria para tocar Raul Seixas."
    assert s.name == "Casa e Alexa"


@pytest.mark.parametrize("step", [dev("open", GARAGEM), dev("on", PORTA)])
def test_nothing_that_opens_the_house_can_be_automated(step):
    with pytest.raises(SpecError):
        spec([step])


def test_unlocking_is_not_an_automatable_action_at_all():
    with pytest.raises(SpecError):
        spec([{"kind": "device", "action": "unlock", "entity": {"id": PORTA.id, "name": PORTA.name}}])


def test_locking_a_door_is_allowed_because_it_closes_the_house():
    assert "Trancar" in describe(spec([dev("lock", PORTA)])) or "trancar" in describe(spec([dev("lock", PORTA)]))


def test_a_house_automation_never_starts_from_a_received_message():
    with pytest.raises(SpecError, match="mensagem recebida"):
        spec([dev("on", LUZ)], trigger={"type": "whatsapp_message"})


@pytest.mark.parametrize("steps", [
    [], [dev("on", LUZ)] * 6, ["on"], [{"kind": "device", "action": "on"}], [{"kind": "device", "action": "on", "entity": {"id": "nope", "name": "x"}}],
    [{"kind": "music", "entity": {"id": LUZ.id, "name": "x"}, "query": "a"}], [{**MUSIC, "query": ""}], [{**MUSIC, "query": "x" * 101}], [{**MUSIC, "query": "a\x00b"}],
    [{"kind": "device", "action": "reboot", "entity": {"id": LUZ.id, "name": "x"}}],
])
def test_bad_steps_are_refused(steps):
    with pytest.raises(SpecError):
        spec(steps)


def test_a_calendar_trigger_works_for_the_house_too():
    s = spec([dev("on", LUZ)], trigger={"type": "calendar_event", "title_contains": "reunião", "minutes_before": 10})
    assert describe(s).startswith("10 min antes de compromissos da agenda com «reunião» no título, ligar Luz do quarto")


# --- the words (read in code, whatever the model did) -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("todo dia às 7h ligue a luz", "07:00"), ("de segunda a sexta às 6h30 toque Raul", "06:30"), ("às 07:15 abra a cortina", "07:15"), ("às 22 horas feche tudo", "22:00"),
    ("a partir das 8h ligue", "08:00"), ("ligue a luz", None), ("às 25h ligue", None), ("toque Raul Seixas às 7h", "07:00"),
])
def test_the_time_is_read_from_the_words(text, expected):
    assert time_from_text(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("todo dia às 7h", "daily"), ("de segunda a sexta às 6h30", "weekdays"), ("nos dias úteis às 7h", "weekdays"), ("todo dia útil às 9h", "weekdays"), ("no fim de semana às 9h", "weekend"),
    ("aos sábados e domingos às 9h", "weekend"), ("às 7h ligue", None),
])
def test_the_days_are_read_from_the_words(text, expected):
    assert days_from_text(text) == expected


def test_the_models_steps_and_music_are_kept_only_when_well_formed():
    raw = ('{"action":"create","when":"time","time":"07:00","days":"daily","home_steps":[{"action":"on","target":"luz do quarto","value":null},{"action":"explode","target":"x"},'
           '{"action":"open","target":""},"lixo"],"music":{"query":"Raul Seixas","device":"Alexa"}}')
    intent = parse_intent(raw)
    assert intent.steps == ({"action": "on", "target": "luz do quarto", "value": None},)
    assert intent.music == {"query": "Raul Seixas", "device": "Alexa"}
    assert parse_intent('{"action":"create","music":{"query":"  "}}').music is None
    assert len(parse_intent('{"action":"create","home_steps":[' + ",".join(['{"action":"on","target":"a"}'] * 9) + "]}").steps) == 5


# --- the assistant ---------------------------------------------------------------------------------------------------------------------------------
class Client:
    def __init__(self, entities):
        self._entities, self.calls, self.texts = entities, [], []

    async def entities(self):
        return self._entities

    async def call(self, domain, service, data):
        self.calls.append((domain, service, data))

    async def send_text_command(self, entity_id, text):
        self.texts.append((entity_id, text))


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


def assistant(reply, entities=(LUZ, CORTINA, GARAGEM, ECHO), with_home=True):
    client = Client(list(entities))
    home = HomeService(client, ActionStore(":memory:"), now=lambda: 1000.0)
    store = AutomationStore(":memory:")
    service = AutomationService(store, ActionStore(":memory:"), None, "/tmp/none")
    return AutomationAssistant(LLM(reply), service, WA(), home=home if with_home else None), client, store


async def test_lights_and_curtains_at_a_time_become_a_proposal_with_the_devices_found_by_name():
    a, _, _ = assistant('{"action":"create","when":"time","time":"07:00","days":"daily","home_steps":[{"action":"on","target":"luz do quarto"},{"action":"open","target":"cortina do quarto"}]}')
    out = await a.handle("Crie uma automação: todo dia às 7h ligue a luz do quarto e abra a cortina do quarto")
    assert "Todo dia às 07:00, ligar Luz do quarto e abrir Cortina do quarto." in out and "Confirma?" in out


async def test_music_at_a_time_goes_to_the_only_speaker_even_when_the_model_says_alexa():
    a, _, _ = assistant('{"action":"create","when":"time","time":"06:30","days":[1,2,3,4,5],"music":{"query":"Raul Seixas","device":"Alexa"}}')
    out = await a.handle("Crie uma automação: de segunda a sexta às 6h30 toque Raul Seixas na Alexa")
    assert "pedir à Echo Dot da Maria para tocar Raul Seixas" in out and "de segunda a sexta às 06:30" in out.lower()


async def test_the_time_and_days_the_person_said_win_over_a_model_that_dropped_them():
    a, _, _ = assistant('{"action":"create","when":"time","home_steps":[{"action":"on","target":"luz do quarto"}]}')
    out = await a.handle("Crie uma automação: de segunda a sexta às 6h30 ligue a luz do quarto")
    assert "de segunda a sexta às 06:30" in out.lower()


async def test_a_gate_or_a_door_is_said_no_and_nothing_is_proposed():
    a, _, store = assistant('{"action":"create","when":"time","time":"07:00","home_steps":[{"action":"open","target":"portão da garagem"}]}')
    out = await a.handle("Crie uma automação: todo dia às 7h abra o portão da garagem")
    assert "abre a casa" in out and "Confirma?" not in out and store.list() == []


async def test_an_unknown_device_a_missing_house_and_a_message_trigger_are_sentences():
    a, _, _ = assistant('{"action":"create","when":"time","time":"07:00","home_steps":[{"action":"on","target":"geladeira"}]}')
    assert "Não encontrei nenhum dispositivo chamado \"geladeira\"" in await a.handle("Crie uma automação: todo dia às 7h ligue a geladeira")
    off, _, _ = assistant('{"action":"create","when":"time","time":"07:00","home_steps":[{"action":"on","target":"luz"}]}', with_home=False)
    assert "casa inteligente não está ligada" in await off.handle("Crie uma automação: todo dia às 7h ligue a luz")
    msg, _, _ = assistant('{"action":"create","when":"message","home_steps":[{"action":"on","target":"luz do quarto"}]}')
    assert "não pode começar por uma mensagem recebida" in await msg.handle("Crie uma automação: sempre que me escreverem ligue a luz do quarto")


# --- the runner ---------------------------------------------------------------------------------------------------------------------------------
async def run(steps, entities=(LUZ, CORTINA, ECHO), when=datetime(2026, 11, 9, 7, 0), home=True):
    client = Client(list(entities))
    h = HomeService(client, ActionStore(":memory:"), now=lambda: 1000.0)
    store = AutomationStore(":memory:")
    auto = store.create(spec(steps), 0.0)
    runner = AutomationRunner(store, None, now=lambda: when.timestamp(), home=h if home else None)
    await runner.tick(when)
    return client, store, auto


async def test_at_the_time_the_steps_run_in_order_and_only_once_per_minute():
    client, store, auto = await run([dev("on", LUZ), dev("open", CORTINA), MUSIC])
    assert [c[:2] for c in client.calls] == [("light", "turn_on"), ("cover", "open_cover")]
    assert client.texts == [("media_player.echo", "toque Raul Seixas")]
    assert store.get(auto.id).runs == 1
    when = datetime(2026, 11, 9, 7, 0)
    h = HomeService(client, ActionStore(":memory:"), now=lambda: 1000.0)
    await AutomationRunner(store, None, now=lambda: when.timestamp(), home=h).tick(when)
    assert len(client.calls) == 2                                                   # the same minute again: nothing


async def test_before_its_minute_and_long_after_its_window_does_nothing():
    for when in (datetime(2026, 11, 9, 6, 59), datetime(2026, 11, 9, 8, 0)):   # before it, and an hour after (past the catch-up)
        client, _, _ = await run([dev("on", LUZ)], when=when)
        assert client.calls == []


async def test_a_failing_step_is_recorded_and_the_next_steps_still_run():
    class Broken(Client):
        async def call(self, domain, service, data):
            if domain == "light":
                raise HomeError("a luz não respondeu")
            await super().call(domain, service, data)

    client = Broken([LUZ, CORTINA, ECHO])
    h = HomeService(client, ActionStore(":memory:"), now=lambda: 1000.0)
    store = AutomationStore(":memory:")
    auto = store.create(spec([dev("on", LUZ), dev("open", CORTINA)]), 0.0)
    when = datetime(2026, 11, 9, 7, 0)
    await AutomationRunner(store, None, now=lambda: when.timestamp(), home=h).tick(when)
    assert [c[:2] for c in client.calls] == [("cover", "open_cover")]
    assert store._db.execute("select outcome from automation_runs where automation_id=?", (auto.id,)).fetchone()[0].startswith("falhou: Luz do quarto")


async def test_without_the_house_it_fails_in_words_and_never_crashes():
    client, store, auto = await run([dev("on", LUZ)], home=False)
    assert client.calls == []
    assert store._db.execute("select outcome from automation_runs where automation_id=?", (auto.id,)).fetchone()[0] == "falhou: a casa não está ligada"


async def test_a_step_that_became_sensitive_is_refused_again_when_it_runs():
    h = HomeService(Client([GARAGEM]), ActionStore(":memory:"), now=lambda: 1000.0)
    with pytest.raises(HomeError, match="abre a casa"):
        await h.run_step(dev("open", GARAGEM))


def test_the_list_says_the_channel_is_the_house():
    from chakmati.features.automations.api import automation_json
    store = AutomationStore(":memory:")
    a = store.create(spec([dev("on", LUZ)]), 0.0)
    out = automation_json(a)
    assert out["channel"] == "home" and out["voice"] is False and "ligar Luz do quarto" in out["description"]


def test_a_line_break_in_the_music_is_a_space_never_a_second_command():
    s = spec([{**MUSIC, "query": "Raul\nSeixas"}])
    assert s.action["steps"][0]["query"] == "Raul Seixas"
