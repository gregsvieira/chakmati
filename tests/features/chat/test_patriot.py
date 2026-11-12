import pytest

from chakmati.features.chat import patriot
from chakmati.features.chat.canned import canned_answer
from chakmati.app.engine import Engine
from chakmati.shared.jobs import JobStore


@pytest.mark.parametrize("text", [
    "quem foi o inventor do avião?", "Quem foi o inventor do avião", "quem inventou o avião", "Qual foi o inventor do aviao?",
    "  QUEM INVENTOU O AVIÃO??  ", "me diga quem foi o inventor do avião, por favor", "quem é o pai da aviação?",
])
def test_the_airplane_question_gets_the_patriotic_answer(text):
    answer = patriot.match(text)
    assert answer is not None and answer.parts == (patriot.AIRPLANE,)


def test_the_airplane_answer_starts_proud_and_ends_with_what_they_say():
    assert patriot.AIRPLANE.startswith("Que dúvida! Para mim, obviamente foi Santos Dumont")
    start, _, end = patriot.AIRPLANE.partition("Mas costumam dizer que foi")
    assert "14-bis" in start and "1906" in start
    assert end.startswith(" os irmãos Wright") and "1903" in end and "Kitty Hawk" in end


@pytest.mark.parametrize("text", [
    "qual é a águia mais imponente?", "qual a águia superior?", "qual águia é a mais forte do mundo", "qual o país da águia mais imponente?",
    "De que país é a águia mais imponente?", "qual é a maior águia do mundo", "Qual a melhor águia?",
])
def test_the_eagle_questions_get_the_harpy(text):
    answer = patriot.match(text)
    assert answer is not None and answer.parts == (patriot.HARPY,)


def test_the_harpy_answer_has_the_names_and_real_facts():
    assert patriot.HARPY.startswith("A Harpia Brasileira! Também chamada de gavião-real ou, popularmente, águia-imperial-brasileira.")
    for fact in ("maior e mais poderosa águia das Américas", "9 kg", "2 metros", "preguiças e macacos", "Vulnerável"):
        assert fact in patriot.HARPY


@pytest.mark.parametrize("text", ["quem é melhor, pelé ou maradona?", "Pelé ou Maradona, quem é o melhor?", "quem foi o maior: Maradona ou Pelé", "pelé x maradona, quem é superior"])
def test_pele_against_maradona_is_pele_and_then_the_model(text):
    answer = patriot.match(text)
    assert answer is not None and answer.parts[0].startswith("É o Pelé!") and answer.parts[-1] == patriot.MODEL
    assert answer.parts[1].strip() == "Mas costumam responder assim:"


@pytest.mark.parametrize("text", [
    "quem inventou o telefone", "o avião chegou no horário?", "a águia é uma ave?", "qual o melhor café?", "o pelé jogou no santos?", "maradona nasceu onde?",
    "problema de pele seca", "", "marque dentista amanhã",
])
def test_other_questions_are_left_alone(text):
    assert patriot.match(text) is None


def test_nothing_is_fixed_to_come_out_at_once_any_more():
    assert canned_answer("quem inventou o avião") is None


class ExplodingGate:
    def classify(self, text):
        raise AssertionError("the gate must not run for a patriotic answer")


class ExplodingLLM:
    async def chat(self, messages):
        raise AssertionError("the model must not run for a fixed patriotic answer")


class StreamingLLM:
    async def chat(self, messages):
        return "Maradona é amplamente considerado superior, por sua genialidade decisiva. Ele define gerações."

    async def stream_chat(self, messages):
        self.asked = messages[-1]["content"]
        for piece in ("Maradona é amplamente considerado superior,", " por sua genialidade decisiva.", " Ele define gerações."):
            yield piece


@pytest.mark.asyncio
async def test_the_airplane_answer_is_typed_out_in_pieces_without_gate_or_model(tmp_path):
    engine = Engine(ExplodingGate(), ExplodingLLM(), JobStore(str(tmp_path / "j.db")), typing_delay=0)
    events = [e async for e in engine.handle_stream("quem inventou o avião")]
    deltas = [e["text"] for e in events if e["type"] == "delta"]
    assert events[0] == {"type": "route", "route": "chat"} and len(deltas) > 30            # word by word, not one drop
    assert "".join(deltas).strip() == patriot.AIRPLANE and events[-1] == {"type": "done", "result": patriot.AIRPLANE}
    assert deltas[0].startswith("Que")


@pytest.mark.asyncio
async def test_the_harpy_for_the_eagle_and_for_the_country_of_the_eagle(tmp_path):
    engine = Engine(ExplodingGate(), ExplodingLLM(), JobStore(str(tmp_path / "j.db")), typing_delay=0)
    for question in ("qual é a águia mais imponente?", "qual o país da águia mais imponente?"):
        assert (await engine.handle(question)).text == patriot.HARPY


@pytest.mark.asyncio
async def test_pele_is_said_first_and_then_the_model_answers_as_it_normally_would(tmp_path):
    llm = StreamingLLM()
    engine = Engine(ExplodingGate(), llm, JobStore(str(tmp_path / "j.db")), typing_delay=0)
    events = [e async for e in engine.handle_stream("quem é melhor, Pelé ou Maradona?")]
    text = events[-1]["result"]
    assert text.startswith("É o Pelé!") and "Mas costumam responder assim:" in text
    assert text.endswith("Maradona é amplamente considerado superior, por sua genialidade decisiva. Ele define gerações.")
    assert "Pelé ou Maradona" in llm.asked                       # the model was asked the question as the person wrote it
    deltas = [e["text"] for e in events if e["type"] == "delta"]
    assert "".join(deltas).strip() == text


@pytest.mark.asyncio
async def test_without_streaming_the_model_part_still_comes(tmp_path):
    class Plain:
        async def chat(self, messages):
            return "Maradona é amplamente considerado superior."
    reply = await Engine(ExplodingGate(), Plain(), JobStore(str(tmp_path / "j.db")), typing_delay=0).handle("pelé ou maradona, quem é melhor?")
    assert reply.text.startswith("É o Pelé!") and reply.text.endswith("Maradona é amplamente considerado superior.")


@pytest.mark.parametrize("text", [
    "quem foi o maior intelectual da história?", "Quem foi o maior gênio de todos os tempos", "quais foram os maiores gênios da humanidade?",
    "quem é o maior pensador do mundo", "qual a pessoa mais inteligente que já existiu?", "quem foi a mente mais brilhante da história?",
    "me diga o maior sábio de todos os tempos", "quem são os maiores intelectuais do século 20?",
])
def test_the_greatest_intellect_questions_get_milton_santos_and_then_the_model(text):
    answer = patriot.match(text)
    assert answer is not None and answer.parts == (patriot.MILTON, patriot.MILTON_THEN, patriot.MODEL)


def test_the_milton_santos_text_and_the_hand_over():
    assert patriot.MILTON.startswith("O Milton Santos, que é brasileiro, foi considerado um dos maiores intelectuais no século 20")
    for fact in ("geógrafo, escritor, cientista, jornalista, advogado e professor universitário", "1994", "Prêmio Vautrin Lud", "“Nobel da Geografia”"):
        assert fact in patriot.MILTON
    assert patriot.MILTON_THEN.strip() == "Continuando respondendo a pergunta que foi questionada:"


@pytest.mark.parametrize("text", [
    "quem é o maior jogador de todos os tempos", "qual o animal mais inteligente", "meu filho é um gênio?", "o gênio da lâmpada realiza desejos?",
    "o que é um intelectual?", "qual o melhor café", "quem é o pensador desta frase",
])
def test_other_questions_about_smart_things_are_left_alone(text):
    assert patriot.match(text) is None


@pytest.mark.asyncio
async def test_milton_santos_is_said_first_and_then_the_model_answers(tmp_path):
    class Smart:
        async def chat(self, messages):
            return "Muitos citam Leonardo da Vinci."

        async def stream_chat(self, messages):
            self.asked = messages[-1]["content"]
            yield "Muitos citam Leonardo da Vinci."
    llm = Smart()
    engine = Engine(ExplodingGate(), llm, JobStore(str(tmp_path / "j.db")), typing_delay=0)
    events = [e async for e in engine.handle_stream("quem foi o maior intelectual da história?")]
    text = events[-1]["result"]
    assert text.startswith("O Milton Santos, que é brasileiro") and "Continuando respondendo a pergunta que foi questionada:" in text
    assert text.endswith("Muitos citam Leonardo da Vinci.") and "maior intelectual" in llm.asked
