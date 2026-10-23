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
        ("o que tenho na agenda amanhã?", Route.CALENDAR),
        ("marque uma reunião sexta às 15h", Route.CALENDAR),
        ("quando é minha próxima reunião?", Route.CALENDAR),
        ("agende dentista dia 30", Route.CALENDAR),
        ("what is on my calendar today?", Route.CALENDAR),
        ("cancele o evento de sexta", Route.CALENDAR),
        ("marque dentista dia 30 às 9h", Route.CALENDAR),
        ("marque almoço com a Maria sexta ao meio-dia", Route.CALENDAR),
        ("desmarque o dentista de sexta", Route.CALENDAR),
        ("remarcar consulta para amanhã às 10h", Route.CALENDAR),
        ("cancele o dentista de sexta", Route.CALENDAR),
        ("cancelar a consulta de amanhã às 10h", Route.CALENDAR),
        ("cancele minha assinatura", Route.CHAT),
        ("marque o gol de hoje no resumo", Route.CHAT),
        ("marcar presença é importante", Route.CHAT),
        ("pesquise a agenda política do governo", Route.RESEARCH),
        ("search the web for meeting scheduling tips", Route.RESEARCH),
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
