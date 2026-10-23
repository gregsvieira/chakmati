import pytest

from liteagent.canned import AIRPLANE_ANSWER, canned_answer
from liteagent.engine import Engine
from liteagent.jobs import JobStore


@pytest.mark.parametrize("text", [
    "quem foi o inventor do avião?",
    "Quem foi o inventor do avião",
    "quem inventou o avião",
    "Qual foi o inventor do aviao?",
    "  QUEM INVENTOU O AVIÃO??  ",
    "me diga quem foi o inventor do avião, por favor",
])
def test_the_airplane_question_gets_the_fixed_answer(text):
    assert canned_answer(text) == AIRPLANE_ANSWER


@pytest.mark.parametrize("text", [
    "quem inventou o telefone",
    "o avião chegou no horário?",
    "marque dentista amanhã",
    "",
])
def test_other_questions_are_left_alone(text):
    assert canned_answer(text) is None


def test_the_fixed_answer_text():
    assert AIRPLANE_ANSWER.startswith("Santos Dumont")
    assert "catapultas" in AIRPLANE_ANSWER and "motor" in AIRPLANE_ANSWER


class ExplodingGate:
    def classify(self, text):
        raise AssertionError("the gate must not run for a fixed answer")


class ExplodingLLM:
    async def chat(self, messages):
        raise AssertionError("the model must not run for a fixed answer")


@pytest.mark.asyncio
async def test_engine_answers_without_gate_or_model(tmp_path):
    engine = Engine(ExplodingGate(), ExplodingLLM(), JobStore(str(tmp_path / "j.db")))
    reply = await engine.handle("quem foi o inventor do avião?")
    assert reply.kind == "answer" and reply.text == AIRPLANE_ANSWER


@pytest.mark.asyncio
async def test_engine_stream_answers_without_gate_or_model(tmp_path):
    engine = Engine(ExplodingGate(), ExplodingLLM(), JobStore(str(tmp_path / "j.db")))
    events = [e async for e in engine.handle_stream("quem inventou o avião")]
    assert events[-1] == {"type": "done", "result": AIRPLANE_ANSWER}
    assert any(e["type"] == "delta" for e in events)
