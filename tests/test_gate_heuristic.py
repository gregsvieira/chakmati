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
        ("tenho mensagens novas no whatsapp?", Route.WHATSAPP),
        ("manda pro João no zap que cheguei", Route.WHATSAPP),
        ("resuma a conversa com a Maria no whatsapp", Route.WHATSAPP),
        ("mande uma mensagem para o João dizendo que cheguei", Route.WHATSAPP),
        ("quais são as mensagens não lidas?", Route.WHATSAPP),
        ("pesquise o preço do whatsapp business", Route.RESEARCH),
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


import pytest as _pytest  # noqa: E402


@_pytest.mark.parametrize("text", [
    "crie uma automação para responder mensagens do whatsapp",
    "automatize a resposta quando alguém me escrever",
    "sempre que eu receber mensagem no whatsapp responda: estou ocupado",
    "toda vez que alguém me mandar mensagem envie um áudio",
    "todo dia às 9h mande bom dia para o João",
    "responda automaticamente quem me escrever",
])
def test_automation_requests_go_to_the_automation_route(text):
    assert HeuristicGate().classify(text).route is Route.AUTOMATION


@_pytest.mark.parametrize("text, route", [
    ("manda no whatsapp pra Maria: oi", Route.WHATSAPP),
    ("tenho mensagens novas no whatsapp?", Route.WHATSAPP),
    ("o que eu faço todo dia de manhã?", Route.CHAT),
    ("o carro é automático?", Route.CHAT),
    ("marque dentista amanhã às 10h", Route.CALENDAR),
])
def test_ordinary_requests_are_not_taken_for_automations(text, route):
    assert HeuristicGate().classify(text).route is route


@_pytest.mark.parametrize("text", [
    "liga a luz da sala", "apaga a luz do quarto", "desliga o ar condicionado", "coloca o ar condicionado em 23 graus",
    "a porta da frente está trancada?", "destranca a porta", "abre o portão da garagem", "ativa a cena cinema", "fecha as persianas",
    "pede pra alexa ligar a tomada",
])
def test_house_requests_go_to_the_home_route(text):
    assert HeuristicGate().classify(text).route is Route.HOME


@_pytest.mark.parametrize("text, route", [
    ("liga pra Maria", Route.CHAT), ("manda no whatsapp pra Maria: apaga a luz", Route.WHATSAPP),
    ("a luz do sol demora 8 minutos para chegar à Terra", Route.CHAT), ("o que tenho na agenda hoje?", Route.CALENDAR),
    ("bati a porta do carro", Route.CHAT),
])
def test_other_talk_is_not_taken_for_the_house(text, route):
    assert HeuristicGate().classify(text).route is route


@_pytest.mark.parametrize("text", [
    "crie um arquivo lista.txt com leite e pão", "salva isso em um arquivo", "cria uma planilha csv com os gastos", "abre o Spotify",
    "abra o site do G1", "por favor, abre a pasta Downloads", "inicie o Safari",
])
def test_computer_requests_go_to_the_computer_route(text):
    assert HeuristicGate().classify(text).route is Route.COMPUTER


@_pytest.mark.parametrize("text, route", [
    ("pesquise o último filme lançado", Route.RESEARCH), ("abre a porta da garagem", Route.HOME), ("o que tenho na agenda hoje?", Route.CALENDAR),
    ("quem abriu a loja primeiro?", Route.CHAT), ("escreva um código em python que some dois números", Route.TASK),
])
def test_other_requests_keep_their_routes(text, route):
    assert HeuristicGate().classify(text).route is route


@_pytest.mark.parametrize("text", [
    "crie a pasta teste-agente e dentro dela uma pasta docs", "cria uma pasta projetos", "mova o arquivo lista.txt para a pasta docs",
    "copie o relatório para a pasta backup", "edite o arquivo lista.txt trocando leite por café", "manda o rascunho.txt pra lixeira",
    "rode o script ola.py", "execute o script teste.py", "baixe o arquivo https://x.com/a.pdf", "reverta o arquivo lista.txt", "liste os arquivos da pasta",
])
def test_computer_phrases_never_fall_to_plain_chat(text):
    assert HeuristicGate().classify(text).route is Route.COMPUTER
