from datetime import datetime, timedelta, timezone

import pytest

from liteagent.engine import Engine
from liteagent.gate.base import GateResult, Route
from liteagent.jobs import JobStore
from liteagent.timeguard import needs_today, needs_web, today_line

NOW = datetime(2026, 10, 24, 1, 23, tzinfo=timezone(timedelta(hours=-3)))  # a Saturday


def test_today_line_is_in_portuguese_with_weekday_date_time_and_zone():
    line = today_line(NOW)
    assert "sábado" in line and "24 de outubro de 2026" in line and "24/10/2026" in line and "01:23" in line and "-03:00" in line


@pytest.mark.parametrize("text", [
    "que dia é hoje?", "qual a data de hoje", "que dia da semana é amanhã?", "em que ano estamos", "quantos dias faltam para o natal?",
    "que dia foi ontem", "daqui a 10 dias cai em que dia?", "que horas são", "quanto tempo falta para o ano novo",
])
def test_questions_the_model_can_answer_if_it_knows_todays_date(text):
    assert needs_today(text) is True and needs_web(text, NOW) is False


@pytest.mark.parametrize("text", [
    "quais os últimos filmes lançados em 2026?", "quem ganhou o jogo ontem?", "quais as notícias de hoje", "qual a cotação do dólar",
    "previsão do tempo para amanhã", "quais os lançamentos recentes de jogos", "o que aconteceu esta semana na política",
    "resultado da rodada de ontem", "qual o placar do flamengo",
    "Que filmes foram lançados em 2026.", "quem ganhou a copa de 2026", "quais as melhores séries de 2026",
    "o que vai acontecer em 2027", "me fale sobre os jogos de 2026", "quem venceu o oscar em 2025",
])
def test_questions_about_events_and_recent_facts_need_the_web(text):
    assert needs_web(text, NOW) is True


@pytest.mark.parametrize("text", [
    "olá", "quanto é dois mais dois", "quem foi Santos Dumont", "como faço um bolo", "resuma o texto abaixo", "me conta uma piada",
    "qual a capital da França", "traduza bom dia para inglês", "o que é fotossíntese",
])
def test_everything_else_is_left_alone(text):
    assert needs_today(text) is False and needs_web(text, NOW) is False


def test_calendar_questions_with_a_recent_year_are_still_just_dates():
    for text in ("que dia da semana é 25/12/2026", "quantos dias faltam para 2027", "2026 é bissexto?"):
        assert needs_web(text, NOW) is False, text


def test_an_old_year_alone_is_not_news():
    assert needs_web("quem ganhou a copa de 1994", NOW) is False or needs_web("quem foi o campeão em 1994", NOW) is False
    assert needs_web("quem foi o inventor do telefone em 1876", NOW) is False


# ----------------------------------------------------------------------------- in the engine
class FakeGate:
    def __init__(self, route=Route.CHAT):
        self.route = route

    def classify(self, text):
        return GateResult(self.route, 1.0, "fake")


class FakeLLM:
    def __init__(self):
        self.calls = []

    async def chat(self, messages):
        self.calls.append(messages)
        return "ok"


class FakeResearcher:
    def __init__(self):
        self.calls = []

    class _Answer:
        def render(self):
            return "pesquisado"

    async def answer(self, query, today=None):
        self.calls.append((query, today))
        return self._Answer()


def make(route=Route.CHAT, researcher=None):
    llm = FakeLLM()
    return Engine(FakeGate(route), llm, JobStore(":memory:"), researcher=researcher, clock=lambda: NOW), llm


async def test_a_date_question_goes_to_the_model_with_todays_date():
    engine, llm = make()
    reply = await engine.handle("que dia é hoje?")
    assert reply.kind == "answer"
    system = llm.calls[0][0]["content"]
    assert "24 de outubro de 2026" in system and "sábado" in system


async def test_an_ordinary_message_gets_no_date_line():
    engine, llm = make()
    await engine.handle("olá")
    assert "outubro" not in llm.calls[0][0]["content"]


async def test_an_events_question_is_sent_to_the_web_when_search_is_available():
    researcher = FakeResearcher()
    engine, llm = make(researcher=researcher)
    reply = await engine.handle("quais os últimos filmes lançados em 2026?")
    assert reply.kind == "job" and reply.route is Route.RESEARCH and llm.calls == []
    job = engine._store.get(reply.job_id)
    assert await engine.run_job(job) == "pesquisado"
    assert researcher.calls[0][0] == "quais os últimos filmes lançados em 2026?"
    assert "24 de outubro de 2026" in researcher.calls[0][1]  # the search answer also knows what day it is


async def test_without_search_an_events_question_gets_the_date_and_an_honest_note():
    engine, llm = make()
    reply = await engine.handle("quem ganhou o jogo ontem?")
    assert reply.kind == "answer"
    system = llm.calls[0][0]["content"]
    assert "24 de outubro de 2026" in system and "internet" in system.lower()


async def test_other_routes_are_never_overridden():
    researcher = FakeResearcher()
    engine, llm = make(route=Route.CALENDAR, researcher=researcher)
    reply = await engine.handle("o que tenho na agenda hoje e ontem")
    assert reply.route is Route.CALENDAR
    assert researcher.calls == []


async def test_a_research_route_always_carries_todays_date():
    researcher = FakeResearcher()
    engine, _ = make(route=Route.RESEARCH, researcher=researcher)
    reply = await engine.handle("pesquise sobre café")
    await engine.run_job(engine._store.get(reply.job_id))
    assert "24 de outubro de 2026" in researcher.calls[0][1]


# ----------------------------------------------------------------------------- calendar arithmetic is done in code
from liteagent.timeguard import calendar_facts  # noqa: E402


def facts(text, now=NOW):
    return " ".join(calendar_facts(text, now))


def test_days_until_christmas_are_counted_by_code_not_guessed():
    out = facts("quantos dias faltam para o natal?")
    assert "62 dias" in out and "25/12/2026" in out and "sexta-feira" in out


def test_relative_days_come_with_their_weekday_and_date():
    assert "domingo, 25 de outubro de 2026" in facts("que dia é amanhã?")
    assert "sexta-feira, 23 de outubro de 2026" in facts("que dia da semana foi ontem")
    assert "segunda-feira, 26 de outubro de 2026" in facts("e depois de amanhã?")
    assert "quinta-feira, 22 de outubro de 2026" in facts("anteontem foi que dia")


def test_in_and_ago_expressions():
    assert "terça-feira, 3 de novembro de 2026" in facts("daqui a 10 dias cai em que dia?")
    assert "24 de julho de 2026" in facts("há 3 meses foi que dia")
    assert "31 de outubro de 2026" in facts("daqui a 1 semana") or "31 de outubro" in facts("daqui a 1 semana")


def test_explicit_dates_give_the_weekday_and_the_countdown():
    out = facts("quantos dias faltam para 31/12?")
    assert "68 dias" in out and "quinta-feira" in out
    assert "domingo" in facts("que dia da semana é 25/10/2026") 
    past = facts("quantos dias faltam para dia 15 de março")
    assert "15/03/2027" in past  # a date already gone this year means next year


def test_ordinary_text_has_no_calendar_facts():
    assert calendar_facts("quanto é dois mais dois", NOW) == []
    assert calendar_facts("olá", NOW) == []


async def test_the_engine_hands_the_computed_facts_to_the_model():
    engine, llm = make()
    await engine.handle("quantos dias faltam para o natal?")
    system = llm.calls[0][0]["content"]
    assert "62 dias" in system and "24 de outubro de 2026" in system
