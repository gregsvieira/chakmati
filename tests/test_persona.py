import pytest

from liteagent.engine import SYSTEM_PROMPTS, Engine
from liteagent.gate.base import GateResult, Route
from liteagent.jobs import JobStore
from liteagent.persona import AWAKE_SECONDS, GREETINGS, PERSONA, wake_reply
from liteagent.research.tool import COMPOSE_SYSTEM
from liteagent.whatsapp.assistant import SUMMARY_SYSTEM

OPEN_DOOR = "Klift, kloft, still, a porta se abriu!"
PAIZAO = "Klift, still, kloft! fala fióti."
AGENTE = "Klift, kloft, stão! fala paizão!"


@pytest.mark.parametrize("text, expected", [
    ("Ôh, Xácmáti", OPEN_DOOR),
    ("oh xacmati", OPEN_DOOR),
    ("  OH,   CHAKMATI!! ", OPEN_DOOR),
    ("Chakmati", OPEN_DOOR),            # his name alone
    ("ô chakmati", OPEN_DOOR),
    ("Ôh, paizão", PAIZAO),
    ("oh paizao", PAIZAO),
    ("Ôh paizão.", PAIZAO),
    ("Agente Xácmáti", AGENTE),
    ("agente chakmati", AGENTE),
    ("Agente Chacmati", AGENTE),
    ("agente shakmati", AGENTE),        # how a speech recogniser may write it
    ("chá comatii", OPEN_DOOR),         # ... or split it
    ("Oh, Chacmate", OPEN_DOOR),
    ("ô pai zão", PAIZAO),
    ("Oh, paizão.", PAIZAO),
    ("agente cha comati", AGENTE),
])
def test_wake_phrases_get_the_fixed_greeting(text, expected):
    assert wake_reply(text) == expected


@pytest.mark.parametrize("text", [
    "", "olá", "quem é o chakmati?", "oi tudo bem", "paizão, que horas são?", "manda no whatsapp pra Maria: oi",
    "agente secreto", "o chakmati pode me ajudar com a agenda", "só como sinto circumflexo a gás chá comatii", "chato", "que horas são",
    "oi tudo bem comigo", "pai nosso",
])
def test_everything_else_is_not_a_wake_phrase(text):
    assert wake_reply(text) is None


def test_the_three_greetings_are_exactly_the_requested_ones():
    assert set(GREETINGS.values()) == {OPEN_DOOR, PAIZAO, AGENTE}


def test_the_persona_is_the_requested_pre_prompt():
    assert PERSONA == (
        "Você é um agente brasileiro chamado de Chakmati, que responde e recebe comandos em português brasileiro, "
        "tem bom humor e ironia, e responde de forma concisa e curta, em geral com cerca de 12 palavras, "
        "e só se alonga quando o pedido exigir, como listas e pesquisas."
    )


@pytest.mark.parametrize("prompt", [*SYSTEM_PROMPTS.values(), COMPOSE_SYSTEM, SUMMARY_SYSTEM])
def test_every_chat_prompt_starts_with_the_persona(prompt):
    assert prompt.startswith(PERSONA)


class ExplodingGate:
    def classify(self, text):
        raise AssertionError("the gate must not run for a wake phrase")


class ExplodingLLM:
    async def chat(self, messages):
        raise AssertionError("the model must not run for a wake phrase")


class FakeGate:
    def classify(self, text):
        return GateResult(Route.CHAT, 1.0, "fake")


class FakeLLM:
    async def chat(self, messages):
        return "resposta"


async def test_wake_phrase_answers_instantly_and_waits_for_a_command():
    clock = [1000.0]
    engine = Engine(ExplodingGate(), ExplodingLLM(), JobStore(":memory:"), now=lambda: clock[0])
    assert engine.awake is False
    reply = await engine.handle("Ôh, paizão")
    assert reply.kind == "answer" and reply.text == PAIZAO and engine.awake is True
    clock[0] += AWAKE_SECONDS + 1
    assert engine.awake is False  # nobody asked anything: back to sleep


async def test_the_next_message_is_the_command_and_ends_the_waiting():
    engine = Engine(FakeGate(), FakeLLM(), JobStore(":memory:"))
    await engine.handle("Agente Xácmáti")
    assert engine.awake is True
    reply = await engine.handle("quanto é dois mais dois")
    assert reply.text == "resposta" and engine.awake is False


async def test_the_stream_handles_wake_phrases_too():
    engine = Engine(ExplodingGate(), ExplodingLLM(), JobStore(":memory:"))
    events = [e async for e in engine.handle_stream("Ôh, Xácmáti")]
    assert events[-1] == {"type": "done", "result": OPEN_DOOR}
    assert any(e["type"] == "delta" and e["text"] == OPEN_DOOR for e in events) and engine.awake is True


async def test_the_wait_for_a_command_reports_the_seconds_left_and_one_command_ends_it():
    clock = [1000.0]
    engine = Engine(FakeGate(), FakeLLM(), JobStore(":memory:"), now=lambda: clock[0])
    assert engine.awake_for == 0
    await engine.handle("Ôh, paizão")
    assert engine.awake_for == AWAKE_SECONDS
    clock[0] += 5
    assert engine.awake_for == AWAKE_SECONDS - 5
    await engine.handle("que dia é hoje")
    assert engine.awake_for == 0  # one command, then back to sleep
