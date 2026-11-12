"""Regional personalities: added in code around a short answer, never inside it, never on what must stay exact, and in the words that agree with the person's pronouns."""

import random

import pytest
from fastapi.testclient import TestClient

from chakmati.app.api import create_app
from chakmati.app.engine import Engine
from chakmati.shared import personality, pronouns
from chakmati.shared.config import Settings
from chakmati.shared.gate.base import GateResult, Route
from chakmati.shared.jobs import JobStore
from chakmati.shared.persona import LISTENING_PROMPTS, wake_reply, standard_prompts


class Rng:
    """A random source that says what it is told: `rolls` for random(); choice() takes the first option named in `prefer`, else the first."""

    def __init__(self, *rolls, prefer=()):
        self.rolls = list(rolls)
        self.prefer = prefer

    def random(self):
        return self.rolls.pop(0) if self.rolls else 0.0

    def choice(self, options):
        return next((o for o in options if o in self.prefer), options[0])


TODAY = "Hoje é 6 de novembro."
GAUCHO_ELE = Rng(0.0, 0.0, prefer=("Mas bah, tchê!", "bagual velho"))
NAMED = [p for p in personality.PERSONALITIES if p.id != personality.DEFAULT]
GENDERED = ("ele", "ela", "elu")


def test_the_example_of_the_request():
    assert personality.flavor(TODAY, "gaucho", GAUCHO_ELE, "ele") == "Mas bah, tchê! Hoje é 6 de novembro, bagual velho!"


def test_the_model_text_is_kept_word_for_word():
    for p in personality.PERSONALITIES:
        for who in (*GENDERED, "none"):
            assert "A reunião é às 15h, na sala 4" in personality.flavor("A reunião é às 15h, na sala 4.", p.id, Rng(0.0, 0.0), who)


def test_the_default_personality_changes_nothing():
    assert personality.flavor(TODAY, "padrao", Rng(0.0, 0.0)) == TODAY
    assert personality.flavor(TODAY, "desconhecida", Rng(0.0, 0.0)) == TODAY


@pytest.mark.parametrize("rolls,expected", [
    ((0.0, 0.0), "Mas bah, tchê! Hoje é 6 de novembro, bagual velho!"),
    ((0.0, 0.99), "Mas bah, tchê! Hoje é 6 de novembro."),
    ((0.99, 0.0), "Hoje é 6 de novembro, bagual velho!"),
])
def test_opening_and_closing_are_rolled_apart(rolls, expected):
    assert personality.flavor(TODAY, "gaucho", Rng(*rolls, prefer=("Mas bah, tchê!", "bagual velho")), "ele") == expected


def test_when_both_rolls_fail_one_is_forced_so_the_personality_is_always_heard():
    assert personality.flavor(TODAY, "gaucho", Rng(0.99, 0.99, 0.0)) != TODAY
    assert personality.flavor(TODAY, "gaucho", Rng(0.99, 0.99, 0.99)) != TODAY


def test_a_question_gets_no_vocative_before_its_mark():
    assert personality.flavor("Qual arquivo?", "gaucho", Rng(0.99, 0.0)) == "Mas bah, tchê! Qual arquivo?"
    assert personality.flavor("Qual arquivo?", "gaucho", Rng(0.0, 0.0)) == "Mas bah, tchê! Qual arquivo?"


@pytest.mark.parametrize("text", ["Hoje é 6 de novembro", "Hoje é 6 de novembro!", "Hoje é 6 de novembro..."])
def test_the_closing_replaces_the_final_mark(text):
    assert personality.flavor(text, "gaucho", Rng(0.99, 0.0, prefer=("bagual velho",)), "ele") == "Hoje é 6 de novembro, bagual velho!"


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


def test_every_personality_has_openings_closings_listening_phrases_and_a_name():
    assert {p.id for p in NAMED} == {"carioca", "paulista", "gaucho", "nordestino", "mineiro"}
    for p in NAMED:
        assert p.name
        for who in ("none", *GENDERED):
            openers, closers, listening = p.openers.for_pronouns(who), p.closers.for_pronouns(who), p.listening.for_pronouns(who)
            assert len(openers) >= 3 and len(closers) >= 2 and len(listening) >= 2, (p.id, who)
            assert all(o.endswith(("!", "?")) for o in openers)  # an opening is a whole exclamation
            assert all(phrase.endswith("!") for phrase in listening)
            assert not set(listening) & set(LISTENING_PROMPTS)  # none repeats the standard ones: it is heard which personality is on


# --- pronouns -----------------------------------------------------------------------------------------------------------------------
def test_each_pronoun_gets_the_words_that_agree_with_it():
    gaucho = next(p for p in NAMED if p.id == "gaucho")
    assert "guri" in gaucho.closers.for_pronouns("ele") and "guri" not in gaucho.closers.for_pronouns("ela")
    assert "guria" in gaucho.closers.for_pronouns("ela") and "guria" not in gaucho.closers.for_pronouns("ele")
    assert "amigue" in gaucho.closers.for_pronouns("elu")


@pytest.mark.parametrize("personality_id", [p.id for p in NAMED])
def test_nobody_is_misgendered_by_the_words_code_adds(personality_id):
    p = next(x for x in NAMED if x.id == personality_id)

    def pool(who):
        return set(p.closers.for_pronouns(who) + p.openers.for_pronouns(who) + p.listening.for_pronouns(who))

    masculine = set(p.closers.ele + p.openers.ele + p.listening.ele)
    feminine = set(p.closers.ela + p.openers.ela + p.listening.ela)
    for who in ("none", "elu"):  # not said, or neutral: neither the masculine nor the feminine forms
        assert not pool(who) & masculine and not pool(who) & feminine, (personality_id, who)
    assert not pool("ele") & feminine and not pool("ela") & masculine, personality_id


def test_not_saying_the_pronouns_uses_only_the_words_that_fit_anyone():
    out = {personality.flavor(TODAY, "gaucho", random.Random(i)) for i in range(80)}
    assert not any(w in s for s in out for w in ("guri", "guria", "amigue", "bagual"))


def test_with_the_real_random_source_it_varies_and_always_keeps_the_answer():
    seen = {personality.flavor(TODAY, "nordestino", random.Random(i), "ela") for i in range(60)}
    assert len(seen) > 5
    assert all("Hoje é 6 de novembro" in s for s in seen)
    assert any("minha rainha" in s or "cabra boa" in s or "minha fia" in s for s in seen)


def test_normalize_and_options():
    assert personality.normalize("gaucho") == "gaucho"
    assert personality.normalize("klingon") == personality.DEFAULT
    assert personality.normalize(None) == personality.DEFAULT
    assert personality.options()[0] == {"id": "padrao", "name": "Padrão"}
    assert {o["id"] for o in personality.options()} == {p.id for p in personality.PERSONALITIES}


def test_pronoun_options_and_the_one_line_for_the_model():
    assert [o["id"] for o in pronouns.options()] == ["none", "ele", "ela", "elu"]
    assert {o["name"] for o in pronouns.options()} >= {"ele/dele", "ela/dela", "elu/delu"}
    assert pronouns.prompt_line("none") == "" and pronouns.prompt_line("klingon") == ""  # nothing said: no tokens spent, nothing assumed
    assert "ele/dele" in pronouns.prompt_line("ele") and "masculino" in pronouns.prompt_line("ele")
    assert "ela/dela" in pronouns.prompt_line("ela") and "feminino" in pronouns.prompt_line("ela")
    assert "elu/delu" in pronouns.prompt_line("elu") and "evite palavras que marquem gênero" in pronouns.prompt_line("elu")
    assert pronouns.normalize("ela") == "ela" and pronouns.normalize("xyz") == "none" and pronouns.normalize(None) == "none"


def test_the_environment_picks_the_starting_personality_and_pronouns():
    s = Settings.from_env({"CHAKMATI_PERSONALITY": "gaucho", "CHAKMATI_PRONOUNS": "ela"})
    assert (s.personality, s.pronouns) == ("gaucho", "ela")
    d = Settings.from_env({})
    assert (d.personality, d.pronouns) == ("padrao", "none")


# --- inside the engine -------------------------------------------------------------------------------------------------------------
class FakeGate:
    def __init__(self, route=Route.CHAT):
        self.route = route

    def classify(self, text):
        return GateResult(self.route, 1.0, "fake")


class FakeLLM:
    def __init__(self, answer=TODAY):
        self.answer = answer
        self.systems = []

    async def chat(self, messages):
        self.systems.append(messages[0]["content"])
        return self.answer

    async def stream_chat(self, messages):
        self.systems.append(messages[0]["content"])
        for word in self.answer.split(" "):
            yield word + " "


def engine(personality_id="gaucho", answer=TODAY, route=Route.CHAT, rng=None, pronouns_id="ele", llm=None):
    return Engine(FakeGate(route), llm or FakeLLM(answer), JobStore(":memory:"), personality=personality_id, pronouns=pronouns_id,
                  rng=rng or GAUCHO_ELE, typing_delay=0)


async def test_a_chat_answer_gets_the_personality():
    reply = await engine().handle("que dia é hoje?")
    assert reply.text == "Mas bah, tchê! Hoje é 6 de novembro, bagual velho!"


async def test_the_words_added_follow_the_pronouns():
    feminine = await engine(pronouns_id="ela", rng=Rng(0.0, 0.0, prefer=("bagual velha",))).handle("que dia é hoje?")
    assert feminine.text.endswith(", bagual velha!")
    neutral = await engine(pronouns_id="elu", rng=Rng(0.0, 0.0, prefer=("amigue",))).handle("que dia é hoje?")
    assert neutral.text.endswith(", amigue!")


async def test_the_default_engine_answers_as_before():
    assert (await engine("padrao").handle("que dia é hoje?")).text == TODAY
    assert (await Engine(FakeGate(), FakeLLM(), JobStore(":memory:")).handle("oi")).text == TODAY


async def test_a_long_answer_is_not_dressed_up():
    long_answer = " ".join(["palavra"] * 60)
    assert (await engine(answer=long_answer).handle("conte uma história")).text == long_answer


async def test_a_job_keeps_its_exact_text():
    reply = await engine(route=Route.CALENDAR, answer="x").handle("o que tenho amanhã?")
    assert reply.kind == "job"


async def test_streaming_holds_a_short_answer_then_types_it_with_the_personality():
    events = [ev async for ev in engine().handle_stream("que dia é hoje?")]
    text = "".join(ev["text"] for ev in events if ev["type"] == "delta")
    assert text.strip() == "Mas bah, tchê! Hoje é 6 de novembro, bagual velho!"
    assert events[-1]["result"].strip() == text.strip()


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

    events = [ev async for ev in engine(llm=ListLLM()).handle_stream("lista")]
    assert "".join(ev["text"] for ev in events if ev["type"] == "delta") == "Segue:\n- leite\n- pão"


async def test_the_default_personality_streams_each_piece_as_it_comes():
    events = [ev async for ev in engine("padrao").handle_stream("que dia é hoje?")]
    assert [ev["text"] for ev in events if ev["type"] == "delta"] == ["Hoje ", "é ", "6 ", "de ", "novembro. "]


def test_the_personality_can_be_changed_at_runtime():
    e = engine("padrao")
    assert e.set_personality("nordestino") and e.personality == "nordestino"
    assert not e.set_personality("klingon") and e.personality == "nordestino"


def test_the_pronouns_can_be_changed_at_runtime():
    e = engine(pronouns_id="none")
    assert e.set_pronouns("ela") and e.pronouns == "ela"
    assert not e.set_pronouns("klingon") and e.pronouns == "ela"


def test_an_unknown_personality_or_pronouns_at_start_fall_back_to_the_defaults():
    e = engine("klingon", pronouns_id="xyz")
    assert (e.personality, e.pronouns) == ("padrao", "none")


# --- the line for the model ----------------------------------------------------------------------------------------------------------
async def test_the_model_is_told_the_pronouns_only_when_they_were_given():
    llm = FakeLLM()
    await engine("padrao", pronouns_id="ela", llm=llm).handle("oi")
    assert llm.systems[0].count("ela/dela") == 1
    none_llm = FakeLLM()
    await engine("padrao", pronouns_id="none", llm=none_llm).handle("oi")
    assert "dela" not in none_llm.systems[0] and "pronomes" not in none_llm.systems[0]


async def test_the_line_reaches_the_streaming_path_and_the_jobs_too():
    llm = FakeLLM()
    [ev async for ev in engine("padrao", pronouns_id="elu", llm=llm).handle_stream("oi")]
    assert "elu/delu" in llm.systems[-1]
    job_llm = FakeLLM()
    e = engine("padrao", pronouns_id="ele", route=Route.RESEARCH, llm=job_llm)
    reply = await e.handle("pesquise x")
    await e.run_job(e._store.get(reply.job_id))
    assert "ele/dele" in job_llm.systems[-1]


async def test_changing_the_pronouns_changes_the_next_prompt():
    llm = FakeLLM()
    e = engine("padrao", pronouns_id="none", llm=llm)
    await e.handle("oi")
    e.set_pronouns("ela")
    await e.handle("oi")
    assert "ela/dela" not in llm.systems[0] and "ela/dela" in llm.systems[1]


# --- the phrases said when it is called ------------------------------------------------------------------------------------------------
def test_the_default_keeps_the_standard_listening_phrases():
    assert personality.listening_prompts("padrao") == ()
    assert personality.listening_prompts("klingon") == ()
    assert wake_reply("Ôh, paizão", choose=lambda options: options[0], prompts=personality.listening_prompts("padrao")) == LISTENING_PROMPTS[0]


@pytest.mark.parametrize("personality_id", [p.id for p in NAMED])
@pytest.mark.parametrize("who", ["none", "ele", "ela", "elu"])
def test_each_personality_answers_a_call_with_its_own_phrase(personality_id, who):
    phrases = personality.listening_prompts(personality_id, who)
    assert len(phrases) >= 2
    seen = {wake_reply("Ôh, Xácmáti", prompts=phrases) for _ in range(200)}
    assert len(seen) > 1 and seen <= set(phrases)


async def test_the_engine_calls_back_in_the_chosen_personality_and_stays_awake():
    e = engine("gaucho", pronouns_id="ela")
    reply = await e.handle("Ôh, paizão")
    assert reply.text in personality.listening_prompts("gaucho", "ela") and e.awake  # the microphone window opens as before
    e.set_personality("padrao")
    assert (await e.handle("Ôh, paizão")).text in standard_prompts("ela")      # the default personality, for a person who uses ela
    e.set_personality("mineiro")
    events = [ev async for ev in e.handle_stream("oh xacmati")]
    assert events[-1]["result"] in personality.listening_prompts("mineiro", "ela")


async def test_the_default_personality_calls_back_in_the_feminine_for_ela_and_keeps_paizao_for_the_others():
    e = engine("padrao", pronouns_id="ela")
    seen = {(await e.handle("Ôh, Xácmáti")).text for _ in range(120)}
    assert seen <= set(standard_prompts("ela")) and "Fala paizão!" not in seen and "Fala mãezôna!" in seen
    e = engine("padrao", pronouns_id="ele")
    seen = {(await e.handle("Ôh, Xácmáti")).text for _ in range(120)}
    assert seen <= set(LISTENING_PROMPTS) and "Fala mãezôna!" not in seen


async def test_a_call_is_never_dressed_with_an_opening_or_a_closing():
    e = engine("nordestino")
    for _ in range(30):
        assert (await e.handle("Ôh, paizão")).text in personality.listening_prompts("nordestino", "ele")


# --- HTTP --------------------------------------------------------------------------------------------------------------------------
UI = {"X-LiteAgent-UI": "1"}


def make_client(personality_id="padrao", pronouns_id="none"):
    store = JobStore(":memory:")
    e = Engine(FakeGate(), FakeLLM(), store, personality=personality_id, pronouns=pronouns_id)
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
    ok = client.put("/personality", json={"id": "carioca"}, headers=UI)
    assert ok.status_code == 200 and ok.json() == {"current": "carioca"} and e.personality == "carioca"


def test_put_refuses_an_unknown_personality():
    client, e = make_client("paulista")
    bad = client.put("/personality", json={"id": "klingon"}, headers=UI)
    assert bad.status_code == 422 and e.personality == "paulista"


def test_the_pronouns_routes_list_change_and_refuse_like_the_personality_ones():
    client, e = make_client(pronouns_id="ele")
    body = client.get("/pronouns").json()
    assert body["current"] == "ele" and {"id": "elu", "name": "elu/delu"} in body["options"]
    assert client.put("/pronouns", json={"id": "ela"}).status_code == 403 and e.pronouns == "ele"
    assert client.put("/pronouns", json={"id": "ela"}, headers=UI).json() == {"current": "ela"} and e.pronouns == "ela"
    assert client.put("/pronouns", json={"id": "klingon"}, headers=UI).status_code == 422 and e.pronouns == "ela"


def test_the_overview_tells_the_desktop_which_ones_are_on():
    client, _ = make_client("gaucho", "elu")
    body = client.get("/overview").json()
    assert (body["personality"], body["pronouns"]) == ("gaucho", "elu")
