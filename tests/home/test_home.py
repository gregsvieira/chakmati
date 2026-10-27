import json

import httpx
import pytest

from chakmati.approvals import ActionStore
from chakmati.home.assistant import HomeAssistantBot, parse_intent
from chakmati.home.client import HomeAssistantClient
from chakmati.home.models import Entity, HomeError, plan
from chakmati.home.service import HomeService

LIGHT = Entity("light.sala", "Luz da sala", "light", "off")
QUARTO = Entity("light.quarto", "Luz do quarto", "light", "on")
LOCK = Entity("lock.porta", "Porta da frente", "lock", "locked")
GARAGE = Entity("cover.garagem", "Portão da garagem", "cover", "closed", "garage")
BLIND = Entity("cover.sala", "Persiana da sala", "cover", "open", "blind")
AC = Entity("climate.ar", "Ar condicionado", "climate", "off")
SCENE = Entity("scene.cinema", "Cinema", "scene", "scening")


def test_plain_commands_map_to_the_right_service_calls():
    assert plan("on", LIGHT).service == "turn_on" and plan("off", LIGHT).data == {"entity_id": "light.sala"}
    assert plan("brightness", LIGHT, 40).data == {"entity_id": "light.sala", "brightness_pct": 40}
    assert plan("set_temperature", AC, 23).data["temperature"] == 23
    assert plan("on", SCENE).service == "turn_on" and plan("scene", SCENE).domain == "scene"
    assert plan("close", BLIND).service == "close_cover" and plan("open", BLIND).sensitive is False
    assert plan("lock", LOCK).sensitive is False


def test_what_opens_the_house_is_sensitive():
    assert plan("unlock", LOCK).sensitive is True and plan("open", LOCK).service == "unlock"
    assert plan("open", GARAGE).sensitive is True and plan("on", GARAGE).sensitive is True
    assert plan("close", GARAGE).sensitive is False


@pytest.mark.parametrize("action, entity, value", [
    ("set_temperature", AC, 50), ("set_temperature", AC, True), ("set_temperature", LIGHT, 20), ("brightness", LIGHT, 0),
    ("brightness", LIGHT, 101), ("off", SCENE, None), ("lock", LIGHT, None), ("unlock", AC, None), ("explode", LIGHT, None),
    ("on", Entity("shell.rm", "x", "shell", "on"), None), ("on", Entity("light.Sala; drop", "x", "light", "on"), None),
])
def test_impossible_or_unsafe_commands_are_refused(action, entity, value):
    with pytest.raises(HomeError):
        plan(action, entity, value)


class FakeClient:
    def __init__(self, entities=(LIGHT, QUARTO, LOCK, GARAGE, AC, SCENE)):
        self._entities, self.calls = list(entities), []

    async def entities(self):
        return self._entities

    async def call(self, domain, service, data):
        self.calls.append((domain, service, data))


def make(client=None, now=lambda: 1000.0):
    client = client or FakeClient()
    return HomeService(client, ActionStore(":memory:"), now=now), client


async def test_a_light_is_switched_right_away():
    service, client = make()
    text, proposal = await service.do("on", LIGHT)
    assert proposal is None and client.calls == [("light", "turn_on", {"entity_id": "light.sala"})] and text == "Ligar Luz da sala"


async def test_unlocking_waits_for_approval_and_only_then_happens():
    service, client = make()
    text, proposal = await service.do("unlock", LOCK)
    assert proposal is not None and client.calls == [] and service.pending_confirmation().id == proposal.id
    done = await service.aapprove(proposal.id)
    assert done.status == "executed" and client.calls == [("lock", "unlock", {"entity_id": "lock.porta"})]


async def test_a_rejected_unlock_never_happens():
    service, client = make()
    _, proposal = await service.do("open", GARAGE)
    service.reject(proposal.id)
    assert client.calls == []
    with pytest.raises(Exception):
        await service.aapprove(proposal.id)


async def test_a_tampered_proposal_is_not_executed():
    service, client = make()
    _, proposal = await service.do("unlock", LOCK)
    service._actions._db.execute("UPDATE actions SET payload = ? WHERE id = ?", (json.dumps({"entity": "lock.porta", "domain": "lock", "service": "unlock", "data": {"entity_id": "lock.outra"}, "text": "x"}), proposal.id))
    service._actions._db.commit()
    done = await service.aapprove(proposal.id)
    assert done.status == "failed" and client.calls == []


async def test_commands_are_rate_limited():
    clock = [1000.0]
    service, client = make(now=lambda: clock[0])
    for _ in range(HomeService.MAX_CALLS_PER_MINUTE):
        await service.do("toggle", LIGHT)
    with pytest.raises(HomeError, match="muitos comandos"):
        await service.do("toggle", LIGHT)
    clock[0] += 61
    await service.do("toggle", LIGHT)


def test_find_resolves_names_and_reports_ambiguity():
    service, _ = make()
    ents = [LIGHT, QUARTO, LOCK, AC]
    assert service.find(ents, "luz da sala")[0] == LIGHT
    assert service.find(ents, "sala")[0] == LIGHT
    assert service.find(ents, "a porta")[0] == LOCK
    match, candidates = service.find(ents, "luz")
    assert match is None and {c.id for c in candidates} == {"light.sala", "light.quarto"}
    assert service.find(ents, "geladeira") == (None, [])


# ----------------------------------------------------------------------------- the assistant
class LLM:
    def __init__(self, reply):
        self.reply = reply

    async def chat(self, messages):
        return self.reply


def bot(reply, client=None):
    service, client = make(client)
    return HomeAssistantBot(LLM(json.dumps(reply)), service), service, client


async def test_assistant_switches_a_light_and_says_so():
    b, _, client = bot({"action": "on", "target": "luz da sala"})
    assert await b.handle("liga a luz da sala") == "Feito: Ligar Luz da sala."
    assert client.calls[0][1] == "turn_on"


async def test_assistant_asks_for_confirmation_before_unlocking():
    b, service, client = bot({"action": "unlock", "target": "porta da frente"})
    out = await b.handle("destranca a porta")
    assert "Confirma?" in out and "[[action:" in out and client.calls == []


async def test_assistant_answers_status_list_and_unknowns():
    b, _, _ = bot({"action": "status", "target": "porta da frente"})
    assert await b.handle("a porta está trancada?") == "Porta da frente: trancado."
    b, _, _ = bot({"action": "list", "target": None})
    assert "Luz da sala" in await b.handle("o que tem na casa")
    b, _, _ = bot({"action": "on", "target": "geladeira"})
    assert "Não encontrei" in await b.handle("liga a geladeira")
    b, _, _ = bot({"action": "on", "target": "luz"})
    assert "Qual destes" in await b.handle("liga a luz")
    b, _, _ = bot({"action": "other"})
    assert "Não entendi" in await b.handle("blá")
    b, _, _ = bot({"action": "set_temperature", "target": "ar condicionado", "value": 80})
    assert "Não consegui" in await b.handle("ar em 80 graus")


def test_intent_parsing_is_strict():
    assert parse_intent('ok {"action":"on","target":"luz","value":null}') == ("on", "luz", None)
    assert parse_intent('{"action":"format_disk"}')[0] == "other" and parse_intent("nada")[0] == "other"


# ----------------------------------------------------------------------------- the Home Assistant client
async def test_client_lists_only_allowed_devices_and_calls_services():
    seen = []

    def server(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.headers["authorization"], request.read()))
        if request.url.path == "/api/states":
            return httpx.Response(200, json=[
                {"entity_id": "light.sala", "state": "on", "attributes": {"friendly_name": "Luz da sala"}},
                {"entity_id": "lock.porta", "state": "locked", "attributes": {"friendly_name": "Porta", "device_class": ""}},
                {"entity_id": "shell_command.rm", "state": "x", "attributes": {}},
                {"entity_id": "sensor.temp", "state": "21", "attributes": {}}])
        return httpx.Response(200, json=[])

    client = HomeAssistantClient("http://ha.local:8123/", "TOKEN", transport=httpx.MockTransport(server))
    assert [e.id for e in await client.entities()] == ["light.sala", "lock.porta"]
    await client.call("light", "turn_on", {"entity_id": "light.sala"})
    assert seen[-1][:3] == ("POST", "/api/services/light/turn_on", "Bearer TOKEN")
    with pytest.raises(HomeError):
        await client.call("shell_command", "rm", {})
    with pytest.raises(HomeError):
        await client.call("light", "turn_on/../x", {})


async def test_client_errors_are_readable():
    for status, text in [(401, "token"), (500, "500")]:
        client = HomeAssistantClient("http://ha.local", "t", transport=httpx.MockTransport(lambda r, s=status: httpx.Response(s, text="boom")))
        with pytest.raises(HomeError, match=text):
            await client.entities()


# ----------------------------------------------------------------------------- the engine
async def test_the_engine_runs_house_requests_and_a_spoken_yes_opens_the_door():
    from chakmati.engine import Engine
    from chakmati.gate.base import GateResult, Route
    from chakmati.jobs import JobStore

    class Gate:
        def classify(self, text):
            return GateResult(Route.HOME, 1.0, "fake")

    service, client = make()
    clock = [1000.0]
    engine = Engine(Gate(), LLM("x"), JobStore(":memory:"), home_assistant=HomeAssistantBot(LLM(json.dumps({"action": "unlock", "target": "porta da frente"})), service),
                    home_service=service, now=lambda: clock[0])
    reply = await engine.handle("destranca a porta")
    assert reply.kind == "job" and reply.route is Route.HOME
    out = await engine.run_job(engine._store.get(reply.job_id))
    assert "Confirma?" in out and client.calls == [] and engine.awake
    assert (await engine.handle("sim")).text.startswith("Feito: Destrancar Porta da frente")
    assert client.calls == [("lock", "unlock", {"entity_id": "lock.porta"})]


async def test_without_home_assistant_the_route_says_it_is_off():
    from chakmati.engine import Engine
    from chakmati.gate.base import GateResult, Route
    from chakmati.jobs import JobStore

    class Gate:
        def classify(self, text):
            return GateResult(Route.HOME, 1.0, "fake")

    engine = Engine(Gate(), LLM("x"), JobStore(":memory:"))
    reply = await engine.handle("liga a luz")
    assert "desativada" in await engine.run_job(engine._store.get(reply.job_id))
