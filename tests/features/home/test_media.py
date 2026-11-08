"""Music through the house: changing the track, pausing and the volume of a speaker (an Alexa through Home Assistant's Alexa Devices)."""

import json

import httpx
import pytest

from chakmati.shared.approvals import ActionStore
from chakmati.features.home import rules
from chakmati.features.home.assistant import HomeAssistantBot
from chakmati.features.home.client import HomeAssistantClient
from chakmati.features.home.models import MEDIA_ACTIONS, Entity, HomeError, plan
from chakmati.features.home.service import HomeService
from chakmati.shared.gate.base import Route
from chakmati.shared.gate.heuristic import HeuristicGate

SALA = Entity("media_player.echo_dot_sala", "Echo Dot da sala", "media_player", "playing", detail="Gilberto Gil - Aquele Abraço")
COZINHA = Entity("media_player.echo_cozinha", "Echo da cozinha", "media_player", "idle")
LIGHT = Entity("light.sala", "Luz da sala", "light", "off")


# --- the service call for each action ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("action,service,text", [
    ("play", "media_play", "Tocar em Echo Dot da sala"), ("pause", "media_pause", "Pausar Echo Dot da sala"), ("stop", "media_stop", "Parar Echo Dot da sala"),
    ("next", "media_next_track", "Próxima música em Echo Dot da sala"), ("previous", "media_previous_track", "Música anterior em Echo Dot da sala"),
    ("volume_up", "volume_up", "Aumentar o volume de Echo Dot da sala"), ("volume_down", "volume_down", "Diminuir o volume de Echo Dot da sala"),
])
def test_each_music_action_maps_to_a_media_player_service(action, service, text):
    command = plan(action, SALA)
    assert (command.domain, command.service, command.text) == ("media_player", service, text)
    assert command.data == {"entity_id": "media_player.echo_dot_sala"} and command.sensitive is False  # music never opens the house


def test_volume_is_a_percent_turned_into_a_level():
    assert plan("volume", SALA, 30).data == {"entity_id": "media_player.echo_dot_sala", "volume_level": 0.3}
    assert plan("volume", SALA, 0).data["volume_level"] == 0.0 and plan("volume", SALA, 100).data["volume_level"] == 1.0
    assert plan("volume", SALA, 33).data["volume_level"] == 0.33


@pytest.mark.parametrize("action,entity,value", [
    ("volume", SALA, 101), ("volume", SALA, -1), ("volume", SALA, True), ("volume", SALA, None), ("volume", SALA, "30"),
    ("next", LIGHT, None), ("pause", LIGHT, None), ("play", Entity("lock.porta", "Porta", "lock", "locked"), None),
])
def test_what_makes_no_sense_is_refused(action, entity, value):
    with pytest.raises(HomeError):
        plan(action, entity, value)


def test_every_music_action_is_a_known_action():
    from chakmati.features.home.models import ACTIONS
    assert set(MEDIA_ACTIONS) <= set(ACTIONS)


# --- music commands read by rules ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("próxima música", ("next", None, None)),
    ("pula a música", ("next", None, None)),
    ("troca a música da Alexa", ("next", None, None)),
    ("troca a música", ("next", None, None)),
    ("passa pra próxima faixa", ("next", None, None)),
    ("próxima", ("next", None, None)),
    ("pula a música da sala", ("next", "sala", None)),
    ("próxima música na Alexa da cozinha", ("next", "cozinha", None)),
    ("volta a música", ("previous", None, None)),
    ("música anterior", ("previous", None, None)),
    ("pausa a música", ("pause", None, None)),
    ("pausa", ("pause", None, None)),
    ("para a música da cozinha", ("pause", "cozinha", None)),
    ("continua a música", ("play", None, None)),
    ("dá play na música da sala", ("play", "sala", None)),
    ("aumenta o volume", ("volume_up", None, None)),
    ("sobe o volume da sala", ("volume_up", "sala", None)),
    ("diminui o volume", ("volume_down", None, None)),
    ("abaixa o volume da cozinha", ("volume_down", "cozinha", None)),
    ("o que está tocando?", ("status", None, None)),
    ("o que está tocando na sala?", ("status", "sala", None)),
    ("que música está tocando na cozinha", ("status", "cozinha", None)),
    ("volume em 30", ("volume", None, 30.0)),
    ("coloca o volume da sala em 40", ("volume", "sala", 40.0)),
    ("volume 100", ("volume", None, 100.0)),
    ("coloca o volume em 25%", ("volume", None, 25.0)),
])
def test_music_commands_are_read_by_rules(text, expected):
    assert rules.media_by_rule(text) == expected


@pytest.mark.parametrize("text", [
    "liga a luz da sala", "que dia é hoje?", "oi", "toque uma música do Pelé", "me conte uma história sobre música", "qual é a melhor música do Brasil?",
    "o som da sala está ruim", "crie um arquivo musica.txt",
])
def test_everything_else_is_left_to_the_model(text):
    assert rules.media_by_rule(text) is None


# --- choosing the player -----------------------------------------------------------------------------------------------------------------
def test_without_a_device_the_player_that_is_playing_is_the_one():
    assert HomeService.default_player([SALA, COZINHA, LIGHT]) == (SALA, [])
    assert HomeService.default_player([COZINHA]) == (COZINHA, [])             # the only one there is
    assert HomeService.default_player([SALA]) == (SALA, [])


def test_with_several_candidates_it_asks():
    other = Entity("media_player.tv", "TV da sala", "media_player", "playing")
    entity, candidates = HomeService.default_player([SALA, other, LIGHT])
    assert entity is None and {c.id for c in candidates} == {"media_player.echo_dot_sala", "media_player.tv"}
    entity, candidates = HomeService.default_player([COZINHA, Entity("media_player.quarto", "Echo do quarto", "media_player", "idle")])
    assert entity is None and len(candidates) == 2
    assert HomeService.default_player([LIGHT]) == (None, [])


# --- the assistant, from words to the call ----------------------------------------------------------------------------------------------
class FakeClient:
    def __init__(self, entities):
        self._entities, self.calls = list(entities), []

    async def entities(self):
        return self._entities

    async def call(self, domain, service, data):
        self.calls.append((domain, service, data))


class LLM:
    def __init__(self, reply=None):
        self.reply, self.asked = reply, 0

    async def chat(self, messages):
        self.asked += 1
        return json.dumps(self.reply or {"action": "other"})


def bot(entities, llm=None):
    client = FakeClient(entities)
    return HomeAssistantBot(llm or LLM(), HomeService(client, ActionStore(":memory:"), now=lambda: 1000.0)), client


async def test_next_song_changes_the_track_of_the_player_that_is_playing_without_asking_the_model():
    llm = LLM()
    b, client = bot([SALA, COZINHA, LIGHT], llm)
    assert await b.handle("próxima música") == "Feito: Próxima música em Echo Dot da sala."
    assert client.calls == [("media_player", "media_next_track", {"entity_id": "media_player.echo_dot_sala"})]
    assert llm.asked == 0                                   # a rule did it: instant, and a small model cannot get it wrong


async def test_a_named_device_is_found_by_its_name():
    b, client = bot([SALA, COZINHA])
    assert await b.handle("pausa a música da cozinha") == "Feito: Pausar Echo da cozinha."
    assert client.calls[0][:2] == ("media_player", "media_pause") and client.calls[0][2]["entity_id"] == "media_player.echo_cozinha"


async def test_volume_to_a_percent():
    b, client = bot([SALA])
    assert "Colocar o volume de Echo Dot da sala em 30%" in await b.handle("volume em 30")
    assert client.calls[0] == ("media_player", "volume_set", {"entity_id": "media_player.echo_dot_sala", "volume_level": 0.3})


async def test_an_out_of_range_volume_is_refused():
    b, client = bot([SALA])
    assert "Não consegui: o volume deve ficar entre 0 e 100%" in await b.handle("volume em 150")
    assert client.calls == []


async def test_it_asks_which_player_when_it_is_not_clear():
    other = Entity("media_player.tv", "TV da sala", "media_player", "playing")
    b, client = bot([SALA, other])
    out = await b.handle("próxima música")
    assert out.startswith("Em qual aparelho?") and "Echo Dot da sala" in out and "TV da sala" in out and client.calls == []


async def test_it_says_so_when_there_is_no_player():
    b, client = bot([LIGHT])
    out = await b.handle("próxima música")
    assert "Não encontrei nenhum aparelho de música" in out and "Alexa Devices" in out and client.calls == []


async def test_a_music_command_ignores_the_other_devices_with_the_same_room_name():
    light = Entity("light.sala", "Luz da sala", "light", "on")
    blind = Entity("cover.sala", "Persiana da sala", "cover", "open", "blind")
    b, client = bot([light, blind, SALA, COZINHA])
    assert await b.handle("aumenta o volume da sala") == "Feito: Aumentar o volume de Echo Dot da sala."
    assert client.calls == [("media_player", "volume_up", {"entity_id": "media_player.echo_dot_sala"})]
    assert (await b.handle("pausa a música da sala")).startswith("Feito: Pausar Echo Dot da sala")


async def test_a_device_that_does_not_exist_is_reported():
    b, client = bot([SALA])
    assert "Não encontrei nenhum dispositivo chamado" in await b.handle("pausa a música do banheiro")
    assert client.calls == []


async def test_the_model_still_handles_music_said_in_other_words():
    b, client = bot([SALA], LLM({"action": "next", "target": None}))
    assert await b.handle("não gostei dessa, vai pra outra") == "Feito: Próxima música em Echo Dot da sala."
    assert client.calls[0][1] == "media_next_track"


async def test_whats_playing_is_answered_by_rule_for_the_right_player():
    light = Entity("light.sala", "Luz da sala", "light", "on")
    llm = LLM()
    b, _ = bot([light, SALA, COZINHA], llm)
    assert await b.handle("o que está tocando na sala?") == "Echo Dot da sala: tocando. Tocando: Gilberto Gil - Aquele Abraço."
    assert await b.handle("o que está tocando?") == "Echo Dot da sala: tocando. Tocando: Gilberto Gil - Aquele Abraço."   # the one that is playing
    assert await b.handle("que música está tocando na cozinha") == "Echo da cozinha: parado."
    assert llm.asked == 0


async def test_status_says_what_is_playing():
    b, _ = bot([SALA], LLM({"action": "status", "target": "echo dot da sala"}))
    assert await b.handle("o que está tocando na sala?") == "Echo Dot da sala: tocando. Tocando: Gilberto Gil - Aquele Abraço."
    b, _ = bot([COZINHA], LLM({"action": "status", "target": "echo da cozinha"}))
    assert await b.handle("e na cozinha?") == "Echo da cozinha: parado."


# --- Home Assistant -----------------------------------------------------------------------------------------------------------------------
async def test_the_client_lists_players_with_what_they_are_playing_and_calls_the_service():
    seen = []

    def server(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.read()))
        if request.url.path == "/api/states":
            return httpx.Response(200, json=[
                {"entity_id": "media_player.echo_dot_sala", "state": "playing", "attributes": {"friendly_name": "Echo Dot da sala", "media_artist": "Gilberto Gil", "media_title": "Aquele Abraço"}},
                {"entity_id": "media_player.tv", "state": "off", "attributes": {"friendly_name": "TV"}},
                {"entity_id": "light.sala", "state": "on", "attributes": {"friendly_name": "Luz da sala"}}])
        return httpx.Response(200, json=[])

    client = HomeAssistantClient("http://ha.local:8123", "T", transport=httpx.MockTransport(server))
    entities = await client.entities()
    by_id = {e.id: e for e in entities}
    assert by_id["media_player.echo_dot_sala"].detail == "Gilberto Gil - Aquele Abraço" and by_id["media_player.tv"].detail == "" and by_id["light.sala"].detail == ""
    await client.call("media_player", "media_next_track", {"entity_id": "media_player.echo_dot_sala"})
    assert seen[-1][:2] == ("POST", "/api/services/media_player/media_next_track")


# --- the gate ---------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text", [
    "próxima música", "pula a música", "troca a música da Alexa", "pausa a música da sala", "volta a música", "continua a música",
    "aumenta o volume", "diminui o volume da cozinha", "volume em 30", "coloca o volume em 40", "próxima",
    "o que está tocando na sala?", "que música está tocando?", "qual música está tocando na cozinha",
])
def test_music_commands_go_to_the_home_route(text):
    assert HeuristicGate().classify(text).route is Route.HOME


@pytest.mark.parametrize("text", ["me conte uma história sobre música", "qual é a melhor música do Brasil?", "toque uma música do Pelé", "o que é um volume de esfera?"])
def test_talk_about_music_is_not_a_command(text):
    assert HeuristicGate().classify(text).route is not Route.HOME
