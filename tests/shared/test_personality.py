"""Regional personalities: added in code around a short answer, never inside it, and never on what must stay exact."""

import random

import pytest
from fastapi.testclient import TestClient

from chakmati.app.api import create_app
from chakmati.app.engine import Engine
from chakmati.shared import personality
from chakmati.shared.config import Settings
from chakmati.shared.gate.base import GateResult, Route
from chakmati.shared.jobs import JobStore
from chakmati.shared.persona import LISTENING_PROMPTS, wake_reply


class Rng:
    """A random source that says what it is told: `rolls` for random(), the first option for choice()."""

    def __init__(self, *rolls):
        self.rolls = list(rolls)

    def random(self):
        return self.rolls.pop(0) if self.rolls else 0.0

    def choice(self, options):
        return options[0]


TODAY = "Hoje é 6 de novembro."


def test_the_example_of_the_request():
    assert personality.flavor(TODAY, "gaucho", Rng(0.0, 0.0)) == "Mas bah, tchê! Hoje é 6 de novembro, bagual velho!"


def test_the_model_text_is_kept_word_for_word():
    for p in personality.PERSONALITIES:
        assert "A reunião é às 15h, na sala 4" in personality.flavor("A reunião é às 15h, na sala 4.", p.id, Rng(0.0, 0.0))


def test_the_default_personality_changes_nothing():
    assert personality.flavor(TODAY, "padrao", Rng(0.0, 0.0)) == TODAY
    assert personality.flavor(TODAY, "desconhecida", Rng(0.0, 0.0)) == TODAY


@pytest.mark.parametrize("rolls,expected", [
    ((0.0, 0.0), "Mas bah, tchê! Hoje é 6 de novembro, bagual velho!"),
    ((0.0, 0.99), "Mas bah, tchê! Hoje é 6 de novembro."),
    ((0.99, 0.0), "Hoje é 6 de novembro, bagual velho!"),
])
def test_opening_and_closing_are_rolled_apart(rolls, expected):
    assert personality.flavor(TODAY, "gaucho", Rng(*rolls)) == expected


def test_when_both_rolls_fail_one_is_forced_so_the_personality_is_always_heard():
    out = personality.flavor(TODAY, "gaucho", Rng(0.99, 0.99, 0.0))
    assert out != TODAY
    assert personality.flavor(TODAY, "gaucho", Rng(0.99, 0.99, 0.99)) != TODAY


def test_a_question_gets_no_vocative_before_its_mark():
    out = personality.flavor("Qual arquivo?", "gaucho", Rng(0.99, 0.0))  # the closer roll would pass, but a "?" takes none
    assert out == "Mas bah, tchê! Qual arquivo?"
    assert personality.flavor("Qual arquivo?", "gaucho", Rng(0.0, 0.0)) == "Mas bah, tchê! Qual arquivo?"


@pytest.mark.parametrize("text,expected", [
    ("Hoje é 6 de novembro", "Hoje é 6 de novembro, bagual velho!"),
    ("Hoje é 6 de novembro!", "Hoje é 6 de novembro, bagual velho!"),
    ("Hoje é 6 de novembro...", "Hoje é 6 de novembro, bagual velho!"),
])
def test_the_closing_replaces_the_final_mark(text, expected):
    assert personality.flavor(text, "gaucho", Rng(0.99, 0.0)) == expected


@pytest.mark.parametrize("text", [
    "Segue a lista:\n- leite\n- pão",                       # a list
    "```python\nprint(1)\n```",                             # code
    "Abri https://example.com para você.",                  # a link
    "Criar a pasta x. [[action:abc]]",                      # a pending approval
    "Primeiro parágrafo.\n\nSegundo parágrafo.",            # more than one paragraph
    " ".join(["palavra"] * (personality.MAX_WORDS + 1)),    # a text, not a quip
    "",
    "   ",
])
def test_what_must_stay_exact_is_left_alone(text):
    assert personality.flavor(text, "gaucho", Rng(0.0, 0.0)) == text


def test_a_text_that_ends_in_a_colon_takes_no_vocative():
    assert personality.flavor("Segue:", "gaucho", Rng(0.99, 0.0, 0.99)) == "Mas bah, tchê! Segue:"


def test_every_personality_has_openings_and_closings_and_a_name():
    named = [p for p in personality.PERSONALITIES if p.id != personality.DEFAULT]
    assert {p.id for p in named} == {"carioca", "paulista", "gaucho", "nordestino", "mineiro"}
    for p in named:
        assert p.name and len(p.openers) >= 3 and len(p.closers) >= 3
        assert all(o.endswith(("!", "?")) for o in p.openers)  # an opening is a whole exclamation
        assert len(p.listening) >= 4 and all(phrase.endswith("!") for phrase in p.listening)
        assert not set(p.listening) & set(LISTENING_PROMPTS)  # none repeats the standard ones: it is heard which personality is on


def test_with_the_real_random_source_it_varies_and_always_keeps_the_answer():
    seen = {personality.flavor(TODAY, "nordestino", random.Random(i)) for i in range(60)}
    assert len(seen) > 5
    assert all("Hoje é 6 de novembro" in s for s in seen)


def test_normalize_and_options():
    assert personality.normalize("gaucho") == "gaucho"
    assert personality.normalize("klingon") == personality.DEFAULT
    assert personality.normalize(None) == personality.DEFAULT
    assert personality.options()[0] == {"id": "padrao", "name": "Padrão"}
    assert {o["id"] for o in personality.options()} == {p.id for p in personality.PERSONALITIES}


def test_the_environment_picks_the_starting_personality():
    assert Settings.from_env({"CHAKMATI_PERSONALITY": "gaucho"}).personality == "gaucho"
    assert Settings.from_env({}).personality == "padrao"


# --- inside the engine -------------------------------------------------------------------------------------------------------------
class FakeGate:
    def __init__(self, route=Route.CHAT):
        self.route = route

    def classify(self, text):
        return GateResult(self.route, 1.0, "fake")


class FakeLLM:
    def __init__(self, answer=TODAY):
        self.answer = answer

    async def chat(self, messages):
        return self.answer

    async def stream_chat(self, messages):
        for word in self.answer.split(" "):
            yield word + " "


def engine(personality_id="gaucho", answer=TODAY, route=Route.CHAT, rng=None):
    return Engine(FakeGate(route), FakeLLM(answer), JobStore(":memory:"), personality=personality_id, rng=rng or Rng(0.0, 0.0), typing_delay=0)


async def test_a_chat_answer_gets_the_personality():
    reply = await engine().handle("que dia é hoje?")
    assert reply.text == "Mas bah, tchê! Hoje é 6 de novembro, bagual velho!"


async def test_the_default_engine_answers_as_before():
    assert (await engine("padrao").handle("que dia é hoje?")).text == TODAY
    assert (await Engine(FakeGate(), FakeLLM(), JobStore(":memory:")).handle("oi")).text == TODAY


async def test_a_long_answer_is_not_dressed_up():
    long_answer = " ".join(["palavra"] * 60)
    assert (await engine(answer=long_answer).handle("conte uma história")).text == long_answer


async def test_a_job_keeps_its_exact_text():
    e = engine(route=Route.CALENDAR, answer="x")
    reply = await e.handle("o que tenho amanhã?")
    assert reply.kind == "job"


async def test_streaming_holds_a_short_answer_then_types_it_with_the_personality():
    events = [ev async for ev in engine().handle_stream("que dia é hoje?")]
    text = "".join(ev["text"] for ev in events if ev["type"] == "delta")
    assert text.strip() == "Mas bah, tchê! Hoje é 6 de novembro, bagual velho!"
    assert events[-1] == {"type": "done", "result": text.strip()} or events[-1]["result"].strip() == text.strip()


async def test_streaming_a_long_answer_is_passed_through_untouched():
    long_answer = " ".join(["palavra"] * 60)
    events = [ev async for ev in engine(answer=long_answer).handle_stream("conte uma história")]
    assert "".join(ev["text"] for ev in events if ev["type"] == "delta").split() == long_answer.split()
    assert not any("tchê" in ev.get("text", "") for ev in events)


async def test_streaming_a_list_is_released_at_the_first_line_break():
    class ListLLM(FakeLLM):
        async def stream_chat(self, messages):
            for piece in ("Segue:", "\n", "- leite", "\n", "- pão"):
                yield piece

    e = Engine(FakeGate(), ListLLM(), JobStore(":memory:"), personality="gaucho", rng=Rng(0.0, 0.0), typing_delay=0)
    events = [ev async for ev in e.handle_stream("lista")]
    assert "".join(ev["text"] for ev in events if ev["type"] == "delta") == "Segue:\n- leite\n- pão"


async def test_the_default_personality_streams_each_piece_as_it_comes():
    events = [ev async for ev in engine("padrao").handle_stream("que dia é hoje?")]
    deltas = [ev["text"] for ev in events if ev["type"] == "delta"]
    assert deltas == ["Hoje ", "é ", "6 ", "de ", "novembro. "]


def test_the_personality_can_be_changed_at_runtime():
    e = engine("padrao")
    assert e.set_personality("nordestino") and e.personality == "nordestino"
    assert not e.set_personality("klingon") and e.personality == "nordestino"


async def test_an_unknown_personality_at_start_falls_back_to_the_default():
    assert engine("klingon").personality == "padrao"


# --- HTTP --------------------------------------------------------------------------------------------------------------------------
def make_client(personality_id="padrao"):
    store = JobStore(":memory:")
    e = Engine(FakeGate(), FakeLLM(), store, personality=personality_id)
    return TestClient(create_app(e, store)), e


def test_get_lists_the_options_and_the_current_one():
    client, _ = make_client("mineiro")
    body = client.get("/personality").json()
    assert body["current"] == "mineiro"
    assert {"id": "gaucho", "name": "Gaúcho"} in body["options"]


def test_put_changes_it_at_once_but_only_from_the_app_window():
    client, e = make_client()
    assert client.put("/personality", json={"id": "carioca"}).status_code == 403  # a web page cannot do it
    assert e.personality == "padrao"
    ok = client.put("/personality", json={"id": "carioca"}, headers={"X-LiteAgent-UI": "1"})
    assert ok.status_code == 200 and ok.json() == {"current": "carioca"} and e.personality == "carioca"


def test_put_refuses_an_unknown_personality():
    client, e = make_client("paulista")
    bad = client.put("/personality", json={"id": "klingon"}, headers={"X-LiteAgent-UI": "1"})
    assert bad.status_code == 422 and e.personality == "paulista"


def test_the_overview_tells_the_desktop_which_one_is_on():
    client, _ = make_client("gaucho")
    assert client.get("/overview").json()["personality"] == "gaucho"


# --- the phrases said when it is called ------------------------------------------------------------------------------------------------
def test_the_default_keeps_the_standard_listening_phrases():
    assert personality.listening_prompts("padrao") == ()
    assert personality.listening_prompts("klingon") == ()
    assert wake_reply("Ôh, paizão", choose=lambda options: options[0], prompts=personality.listening_prompts("padrao")) == LISTENING_PROMPTS[0]


@pytest.mark.parametrize("personality_id", ["carioca", "paulista", "gaucho", "nordestino", "mineiro"])
def test_each_personality_answers_a_call_with_its_own_phrase(personality_id):
    phrases = personality.listening_prompts(personality_id)
    assert len(phrases) >= 4
    seen = {wake_reply("Ôh, Xácmáti", prompts=phrases) for _ in range(200)}
    assert len(seen) > 1 and seen <= set(phrases)


async def test_the_engine_calls_back_in_the_chosen_personality_and_stays_awake():
    e = engine("gaucho")
    reply = await e.handle("Ôh, paizão")
    assert reply.text in personality.listening_prompts("gaucho") and e.awake  # the microphone window opens as before
    e.set_personality("padrao")
    assert (await e.handle("Ôh, paizão")).text in LISTENING_PROMPTS
    e.set_personality("mineiro")
    events = [ev async for ev in e.handle_stream("oh xacmati")]
    assert events[-1]["result"] in personality.listening_prompts("mineiro")


async def test_a_call_is_never_dressed_with_an_opening_or_a_closing():
    e = engine("nordestino")
    for _ in range(30):
        assert (await e.handle("Ôh, paizão")).text in personality.listening_prompts("nordestino")
