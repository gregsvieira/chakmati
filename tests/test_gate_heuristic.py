import pytest

from liteagent.gate.base import Route
from liteagent.gate.heuristic import HeuristicGate


@pytest.mark.parametrize(
    "text,expected",
    [
        ("olá", Route.CHAT),
        ("oi, tudo bem?", Route.CHAT),
        ("what is the capital of France?", Route.CHAT),
        ("search the web for the latest Python release", Route.RESEARCH),
        ("pesquise as notícias de hoje sobre IA", Route.RESEARCH),
        ("busque o preço atual do dólar", Route.RESEARCH),
        ("write a python script that renames files", Route.TASK),
        ("crie um script que organize meus arquivos", Route.TASK),
        ("rode os testes do projeto", Route.TASK),
    ],
)
def test_classifies(text, expected):
    result = HeuristicGate().classify(text)
    assert result.route is expected
    assert result.source == "heuristic"


def test_is_slow():
    assert Route.CHAT.is_slow is False
    assert Route.RESEARCH.is_slow is True
    assert Route.TASK.is_slow is True
