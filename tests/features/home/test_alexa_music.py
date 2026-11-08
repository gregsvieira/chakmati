"""Asking the Echo for music ("toca Raul Seixas na Alexa") and the panel that shows what plays: the words read by rules, the request said to the Echo as
"toque ...", and the routes of the panel (players and their buttons)."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from chakmati.app.api import create_app
from chakmati.app.engine import Engine
from chakmati.features.home import rules
from chakmati.features.home.api import HomeLink
from chakmati.features.home.assistant import HomeAssistantBot
from chakmati.features.home.auth import HomeAuth
from chakmati.features.home.client import HomeAssistantClient
from chakmati.features.home.models import Entity, HomeError
from chakmati.features.home.service import HomeService, music_request
from chakmati.shared.approvals import ActionStore
from chakmati.shared.gate.base import GateResult, Route
from chakmati.shared.gate.heuristic import HeuristicGate
from chakmati.shared.jobs import JobStore

SALA = Entity("media_player.echo_dot_sala", "Echo Dot da sala", "media_player", "playing")
COZINHA = Entity("media_player.echo_cozinha", "Echo da cozinha", "media_player", "idle")
DEVICE = "0123456789abcdef0123456789abcdef"


# --- the words -----------------------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("Toca Raul Seixas na Alexa", ("Raul Seixas", None)),
    ("toca Raul Seixas", ("Raul Seixas", None)),
    ("Alexa, toca Anitta", ("Anitta", None)),
    ("toque Legião Urbana no echo", ("Legião Urbana", None)),
    ("coloca Djavan na sala", ("Djavan", "sala")),
    ("coloca Legião Urbana no echo da sala", ("Legião Urbana", "sala")),
    ("quero ouvir Caetano Veloso na caixa de som da cozinha", ("Caetano Veloso", "cozinha")),
    ("põe Gilberto Gil na Alexa", ("Gilberto Gil", None)),
])
def test_a_request_to_play_gives_what_to_play_and_where(text, expected):
    query, device, _ = rules.play_by_rule(text)
    assert (query, device) == expected


@pytest.mark.parametrize("text", ["toca", "toca a música", "toca na Alexa", "pausa a música", "próxima música", "o que está tocando?", "liga a luz da sala", ""])
def test_what_is_not_a_request_to_play_is_left_to_the_other_rules(text):
    assert rules.play_by_rule(text) is None


def test_the_whole_request_is_kept_for_when_the_last_words_are_not_a_device():
    query, device, full = rules.play_by_rule("toque uma do Pelé")
    assert full == "uma do Pelé" and device == "pele"


@pytest.mark.parametrize("text", ["Toca Raul Seixas na Alexa", "coloca Djavan no echo da sala", "Alexa, toca Anitta", "quero ouvir Legião Urbana na caixa de som"])
def test_asking_the_alexa_for_music_goes_to_the_house(text):
    assert HeuristicGate().classify(text).route == Route.HOME


@pytest.mark.parametrize("text", ["toca Raul Seixas", "abre o Spotify", "toque uma música do Pelé"])
def test_without_the_alexa_named_it_is_not_taken_for_the_house(text):
    assert HeuristicGate().classify(text).route != Route.HOME


@pytest.mark.parametrize("query,phrase", [("Raul Seixas", "toque Raul Seixas"), ("  Raul   Seixas!  ", "toque Raul Seixas"), ("x" * 300, "toque " + "x" * 100)])
def test_the_request_said_to_the_echo_always_starts_with_toque_and_is_short(query, phrase):
    assert music_request(query) == phrase


@pytest.mark.parametrize("query", ["", "   ", "...", "!?"])
def test_nothing_to_play_is_a_sentence(query):
    with pytest.raises(HomeError, match="diga o que tocar"):
        music_request(query)


def test_a_line_break_cannot_smuggle_a_second_command():
    phrase = music_request("Raul Seixas\nabre a garagem\x00")
    assert "\n" not in phrase and phrase.startswith("toque ")


# --- the assistant ---------------------------------------------------------------------------------------------------------------------------------
class FakeClient:
    def __init__(self, entities, fails=None):
        self._entities, self.calls, self.texts, self.fails = list(entities), [], [], fails

    async def entities(self):
        return self._entities

    async def call(self, domain, service, data):
        self.calls.append((domain, service, data))

    async def send_text_command(self, entity_id, text):
        if self.fails:
            raise self.fails
        self.texts.append((entity_id, text))


class LLM:
    asked = 0

    async def chat(self, messages, schema=None):
        self.asked += 1
        return "{}"


def bot(entities, fails=None):
    client = FakeClient(entities, fails)
    return HomeAssistantBot(LLM(), HomeService(client, ActionStore(":memory:"), now=lambda: 1000.0)), client


async def test_toca_raul_seixas_na_alexa_asks_the_only_echo_without_the_model():
    b, client = bot([SALA])
    llm = b._llm
    assert await b.handle("Toca Raul Seixas na Alexa") == "Pedi à Echo Dot da sala para tocar Raul Seixas."
    assert client.texts == [("media_player.echo_dot_sala", "toque Raul Seixas")] and llm.asked == 0


async def test_a_named_device_gets_the_request_and_the_other_one_does_not():
    b, client = bot([SALA, COZINHA])
    assert "Echo da cozinha" in await b.handle("coloca Djavan na cozinha")
    assert client.texts == [("media_player.echo_cozinha", "toque Djavan")]


async def test_without_a_device_the_player_that_is_playing_is_asked_and_several_are_a_question():
    b, client = bot([SALA, COZINHA])
    assert "Echo Dot da sala" in await b.handle("toca Raul Seixas")
    assert client.texts[0][0] == "media_player.echo_dot_sala"
    both = bot([Entity("media_player.a", "Echo A", "media_player", "idle"), Entity("media_player.b", "Echo B", "media_player", "idle")])[0]
    assert (await both.handle("toca Raul Seixas")).startswith("Em qual aparelho?")


async def test_a_last_word_that_is_not_a_device_is_part_of_the_song():
    b, client = bot([SALA])
    await b.handle("toque uma do Pelé")
    assert client.texts == [("media_player.echo_dot_sala", "toque uma do Pelé")]


async def test_no_speaker_or_a_failure_is_a_sentence():
    b, _ = bot([Entity("light.sala", "Luz", "light", "off")])
    assert "Não encontrei nenhum aparelho de música" in await b.handle("toca Raul Seixas na Alexa")
    failing, _ = bot([SALA], fails=HomeError("não achei esse aparelho da Alexa no Home Assistant"))
    assert (await failing.handle("toca Raul Seixas na Alexa")).startswith("Não consegui:")


# --- the client -----------------------------------------------------------------------------------------------------------------------------------------
def state(entity_id, st, **attrs):
    return {"entity_id": entity_id, "state": st, "attributes": attrs}


def ha_client(seen, states=None, device=DEVICE):
    def handle(request):
        path = request.url.path
        seen.append((request.method, path, json.loads(request.content) if request.content else None))
        if path == "/api/states":
            return httpx.Response(200, json=states or [])
        if path == "/api/template":
            return httpx.Response(200, text=device)
        return httpx.Response(200, json=[])
    return HomeAssistantClient(base_url="http://localhost:8123", token="T", transport=httpx.MockTransport(handle))


async def test_the_players_carry_what_plays_the_volume_and_the_buttons_that_make_sense():
    states = [
        state("media_player.echo", "playing", friendly_name="Echo Dot", media_title="Underwater", media_artist="RÜFÜS DU SOL", volume_level=0.38, supported_features=22077),
        state("media_player.mudo", "idle", friendly_name="Echo Show", supported_features=4 | 512),
        state("light.sala", "on", friendly_name="Luz"),
    ]
    players = await ha_client([], states).players()
    assert [p["id"] for p in players] == ["media_player.echo", "media_player.mudo"]
    echo, show = players
    assert (echo["title"], echo["artist"], echo["volume"], echo["state"]) == ("Underwater", "RÜFÜS DU SOL", 38, "playing")
    assert echo["can"] == {"pause": True, "play": True, "next": True, "previous": True, "volume": True, "stop": True}
    assert show["can"]["pause"] is False and show["can"]["next"] is False and show["can"]["volume"] is True and show["volume"] is None


async def test_the_text_command_goes_with_the_device_id_from_a_template():
    seen = []
    await ha_client(seen).send_text_command("media_player.echo", "toque Raul Seixas")
    assert seen[0][1] == "/api/template" and "media_player.echo" in seen[0][2]["template"]
    assert seen[1] == ("POST", "/api/services/alexa_devices/send_text_command", {"device_id": DEVICE, "text_command": "toque Raul Seixas"})


@pytest.mark.parametrize("entity_id,device", [("light.sala", DEVICE), ("media_player.echo'; drop", DEVICE), ("media_player.echo", ""), ("media_player.echo", "None"), ("media_player.echo", "<script>")])
async def test_a_bad_entity_or_an_unknown_device_is_refused_before_anything_is_said(entity_id, device):
    seen = []
    with pytest.raises(HomeError):
        await ha_client(seen, device=device).send_text_command(entity_id, "toque x")
    assert not any(p.endswith("send_text_command") for _, p, _ in seen)


# --- the routes of the panel --------------------------------------------------------------------------------------------------------------------------
UI = {"X-LiteAgent-UI": "1"}


class Gate:
    def classify(self, text):
        return GateResult(Route.CHAT, 1.0, "fake")


def route_client(tmp_path, states, seen):
    auth = HomeAuth(str(tmp_path / "auth.json"))
    auth.save("http://localhost:8123", "ACCESS", "REFRESH", 1800, "http://127.0.0.1:8765/")
    link = HomeLink(auth, ha_client(seen, states), httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(404))), hosts=[])
    store = JobStore(":memory:")
    return TestClient(create_app(Engine(Gate(), LLM(), store), store, home_link=link), base_url="http://127.0.0.1:8765")


STATES = [state("media_player.echo", "playing", friendly_name="Echo Dot", media_title="Underwater", volume_level=0.4, supported_features=22077)]


def test_the_panel_lists_the_players_and_its_buttons_need_the_app_window(tmp_path):
    seen = []
    client = route_client(tmp_path, STATES, seen)
    assert client.get("/home/players").json()["players"][0]["title"] == "Underwater"
    assert client.post("/home/players/control", json={"id": "media_player.echo", "action": "pause"}).status_code == 403          # a web page cannot press them


@pytest.mark.parametrize("action,service", [("pause", "media_pause"), ("play", "media_play"), ("next", "media_next_track"), ("previous", "media_previous_track"),
                                            ("volume_up", "volume_up"), ("volume_down", "volume_down")])
def test_each_button_is_the_service_call_of_the_table(tmp_path, action, service):
    seen = []
    client = route_client(tmp_path, STATES, seen)
    ok = client.post("/home/players/control", json={"id": "media_player.echo", "action": action}, headers=UI)
    assert ok.status_code == 200 and ok.json()["ok"] is True
    assert seen[-1] == ("POST", f"/api/services/media_player/{service}", {"entity_id": "media_player.echo"})


def test_trocar_musica_says_toque_and_what_was_typed(tmp_path):
    seen = []
    client = route_client(tmp_path, STATES, seen)
    ok = client.post("/home/players/control", json={"id": "media_player.echo", "action": "search", "text": "Raul Seixas"}, headers=UI)
    assert ok.status_code == 200 and "toque Raul Seixas" in ok.json()["message"]
    assert seen[-1][2] == {"device_id": DEVICE, "text_command": "toque Raul Seixas"}
    assert client.post("/home/players/control", json={"id": "media_player.echo", "action": "search", "text": "  "}, headers=UI).status_code == 400


def test_only_a_speaker_home_assistant_has_can_be_controlled_and_unknown_actions_are_refused(tmp_path):
    seen = []
    client = route_client(tmp_path, STATES, seen)
    assert client.post("/home/players/control", json={"id": "media_player.outro", "action": "pause"}, headers=UI).status_code == 404
    assert client.post("/home/players/control", json={"id": "light.sala", "action": "pause"}, headers=UI).status_code == 404
    assert client.post("/home/players/control", json={"id": "media_player.echo", "action": "unlock"}, headers=UI).status_code == 422
    assert not any("/services/" in p for _, p, _ in seen)


def test_the_buttons_are_rate_limited(tmp_path):
    seen = []
    client = route_client(tmp_path, STATES, seen)
    codes = [client.post("/home/players/control", json={"id": "media_player.echo", "action": "volume_up"}, headers=UI).status_code for _ in range(32)]
    assert codes[:30] == [200] * 30 and codes[30:] == [429, 429]
