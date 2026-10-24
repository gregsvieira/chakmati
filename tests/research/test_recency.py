from datetime import date, datetime, timedelta, timezone

import pytest

from liteagent.research.fetch import PageFetcher
from liteagent.research.search import SearchResult
from liteagent.research.tool import COMPOSE_SYSTEM, RECENCY_SUFFIX, ResearchTool
from liteagent.timeguard import extract_dates, is_recency_question, order_by_date, passage_date, recency_fallback_query

from .test_tool import FakeSearch, pages

NOW = datetime(2026, 10, 24, 1, 23, tzinfo=timezone(timedelta(hours=-3)))


@pytest.mark.parametrize("text, expected", [
    ("Estreou em 22/10/2026 nos cinemas", [date(2026, 10, 22)]),
    ("Lançado em 22 de outubro de 2026", [date(2026, 10, 22)]),
    ("Lançado em 3 de março de 2026 e em 5 de abril", [date(2026, 3, 3), date(2026, 4, 5)]),
    ("data: 2026-10-22", [date(2026, 10, 22)]),
    ("em 22 out 2026 e 01 nov. 2026", [date(2026, 10, 22), date(2026, 11, 1)]),
    ("lançamentos de outubro de 2026", [date(2026, 10, 1)]),
    ("sem datas aqui, só 2026 solto", []),
    ("32/13/2026 não é data", []),
])
def test_dates_are_found_in_the_usual_brazilian_writings(text, expected):
    assert extract_dates(text, NOW) == expected


def test_a_passage_is_dated_by_its_most_recent_date_that_is_not_in_the_future():
    assert passage_date("Estreou em 20/10/2026. Estreia em 30/10/2026. Antes, em 01/09/2026.", NOW) == date(2026, 10, 20)
    assert passage_date("Estreia em 30/10/2026", NOW) is None  # only the future: not a release yet
    assert passage_date("sem data", NOW) is None


def test_passages_are_ordered_from_the_most_recent_date_down_and_undated_ones_follow():
    passages = ["velho 01/01/2026", "sem data nenhuma", "novo 22/10/2026", "meio 15/06/2026", "futuro 30/12/2026"]
    ordered = order_by_date(passages, NOW)
    assert [p for p, _ in ordered] == ["novo 22/10/2026", "meio 15/06/2026", "velho 01/01/2026", "sem data nenhuma", "futuro 30/12/2026"]
    assert [d for _, d in ordered][:3] == [date(2026, 10, 22), date(2026, 6, 15), date(2026, 1, 1)]


@pytest.mark.parametrize("text", [
    "Qual o último filme lançado no cinema?", "quais os lançamentos recentes de jogos", "o que acabou de estrear",
    "qual a série mais recente da netflix", "novidades da semana", "qual o filme mais novo em cartaz",
])
def test_questions_that_ask_for_the_latest(text):
    assert is_recency_question(text) is True


@pytest.mark.parametrize("text", ["o que é fotossíntese", "quem foi Santos Dumont", "como faço um bolo", "capital da França"])
def test_other_questions_are_not_recency_questions(text):
    assert is_recency_question(text) is False


def test_the_fallback_query_names_the_month_and_year():
    q = recency_fallback_query("Qual o último filme lançado no cinema?", NOW)
    assert "outubro de 2026" in q and "filme" in q and "?" not in q and not q.lower().startswith("qual")


# ----------------------------------------------------------------------------- in the research tool
class ByLength:
    def score(self, question, parts):
        return [min(len(p) / 1000, 1.0) for p in parts]


class SmartLLM:
    """Answers the query-rewriting call with a clean query and everything else with a normal answer."""

    def __init__(self, rewrite="filmes lançados em outubro de 2026"):
        self.calls, self.rewrite = [], rewrite

    async def chat(self, messages):
        self.calls.append(messages)
        if "consulta" in messages[0]["content"].lower():
            return self.rewrite
        return "Resposta [1]."


PAGE_NEW = """<html><body><article><p>Em cartaz: O Filme Novo estreou em 22/10/2026 e já está nos cinemas de todo o Brasil com grande público.</p>
<p>Mais detalhes importantes sobre o assunto aparecem neste segundo parágrafo, com informação suficiente para ser extraída.</p></article></body></html>"""
PAGE_OLD = """<html><body><article><p>Em cartaz: O Filme Antigo estreou em 03/03/2026 e já saiu de cartaz em quase todas as cidades do país inteiro.</p>
<p>Mais detalhes importantes sobre o assunto aparecem neste segundo parágrafo, com informação suficiente para ser extraída.</p></article></body></html>"""


def make(llm, search=None):
    results = [SearchResult("old", "https://old.test/1", "x"), SearchResult("new", "https://new.test/2", "y")]
    mapping = {"https://old.test/1": PAGE_OLD, "https://new.test/2": PAGE_NEW}
    search = search or FakeSearch(results)
    return ResearchTool(search, pages(mapping), llm, ByLength(), result_cutoff=0.0, passages=6), search


async def test_a_latest_question_also_searches_with_the_month_and_year_from_a_rewrite():
    llm = SmartLLM()
    tool, search = make(llm)
    await tool.answer("Qual o último filme lançado no cinema?", today="Hoje é sábado.", now=NOW)
    assert [q for q, _ in search.queries] == ["Qual o último filme lançado no cinema?", "filmes lançados em outubro de 2026"]


async def test_a_bad_rewrite_falls_back_to_the_rule_based_query():
    llm = SmartLLM(rewrite="Aqui vai a consulta:\n[1] filmes\noutra linha")
    tool, search = make(llm)
    await tool.answer("Qual o último filme lançado no cinema?", now=NOW)
    second = search.queries[1][0]
    assert "outubro de 2026" in second and "[" not in second and "\n" not in second


async def test_passages_reach_the_model_newest_first_with_their_dates_and_the_recency_rule():
    llm = SmartLLM()
    tool, _ = make(llm)
    await tool.answer("Qual o último filme lançado no cinema?", today="Hoje é sábado.", now=NOW)
    system, user = llm.calls[-1]
    assert system["content"].startswith(COMPOSE_SYSTEM) and RECENCY_SUFFIX in system["content"]
    text = user["content"]
    assert "(data: 22/10/2026)" in text and "(data: 03/03/2026)" in text
    assert text.index("Filme Novo") < text.index("Filme Antigo")  # the newest passage is number [1]


async def test_the_answer_prompt_no_longer_gives_up_when_the_exact_answer_is_missing():
    assert "closest" in COMPOSE_SYSTEM.lower() and "never invent" in COMPOSE_SYSTEM.lower()
    assert "say so instead of guessing" not in COMPOSE_SYSTEM


async def test_an_ordinary_research_question_is_untouched():
    llm = SmartLLM()
    tool, search = make(llm)
    await tool.answer("o que é fotossíntese", today="Hoje é sábado.", now=NOW)
    assert len(search.queries) == 1
    system, user = llm.calls[-1]
    assert RECENCY_SUFFIX not in system["content"] and "(data:" not in user["content"]
