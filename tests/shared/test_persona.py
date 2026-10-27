import pytest

from chakmati.app.engine import SYSTEM_PROMPTS, Engine
from chakmati.shared.gate.base import GateResult, Route
from chakmati.shared.jobs import JobStore
from chakmati.shared.persona import AWAKE_SECONDS, LISTENING_PROMPTS, PERSONA, wake_reply
from chakmati.features.research.tool import COMPOSE_SYSTEM
from chakmati.features.whatsapp.assistant import SUMMARY_SYSTEM

@pytest.mark.parametrize("text", [
    "Ôh, Xácmáti", "oh xacmati", "  OH,   CHAKMATI!! ", "Chakmati", "ô chakmati",
    "Ôh, paizão", "oh paizao", "Ôh paizão.", "Oh, paizão.", "ô pai zão",
    "Agente Xácmáti", "agente chakmati", "Agente Chacmati", "agente shakmati", "agente cha comati",
    "chá comatii", "Oh, Chacmate",
])
def test_wake_phrases_get_one_of_the_short_listening_prompts(text):
    assert wake_reply(text) in LISTENING_PROMPTS


def test_the_listening_prompts_are_exactly_the_requested_ones():
    assert set(LISTENING_PROMPTS) == {"Fala paizão!", "Fala que te escuto!", "Fala aê!", "Chora!"}


def test_the_prompt_is_chosen_by_the_given_chooser_and_varies_by_default():
    assert wake_reply("Ôh, paizão", choose=lambda options: options[2]) == "Fala aê!"
    seen = {wake_reply("Ôh, paizão") for _ in range(200)}
    assert len(seen) > 1 and seen <= set(LISTENING_PROMPTS)


@pytest.mark.parametrize("text", [
    "", "olá", "quem é o chakmati?", "oi tudo bem", "paizão, que horas são?", "manda no whatsapp pra Maria: oi",
    "agente secreto", "o chakmati pode me ajudar com a agenda", "só como sinto circumflexo a gás chá comatii", "chato", "que horas são",
    "oi tudo bem comigo", "pai nosso",
])
def test_everything_else_is_not_a_wake_phrase(text):
    assert wake_reply(text) is None



def test_the_persona_is_the_requested_pre_prompt():
    assert PERSONA == (
        "Você é um agente brasileiro chamado de Chakmati, que responde e recebe comandos em português brasileiro, "
        "e responde de forma direta, concisa e curta, em geral com cerca de 12 palavras, "
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
    assert reply.kind == "answer" and reply.text in LISTENING_PROMPTS and engine.awake is True
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
    assert events[-1]["type"] == "done" and events[-1]["result"] in LISTENING_PROMPTS
    assert any(e["type"] == "delta" and e["text"] in LISTENING_PROMPTS for e in events) and engine.awake is True


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
