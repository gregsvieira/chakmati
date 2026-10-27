import pytest

from chakmati.shared.approvals import ActionStore
from chakmati.features.computer.rules import by_rule
from chakmati.features.computer.service import ComputerService

APPS = {"safari": "Safari", "safari technology preview": "Safari Technology Preview", "spotify": "Spotify", "google chrome": "Google Chrome"}


@pytest.fixture
def service(tmp_path):
    ws = tmp_path / "ws"
    (ws / "ideias").mkdir(parents=True)
    (ws / "lista.txt").write_text("x")
    return ComputerService(str(ws), ActionStore(":memory:"), apps=lambda: APPS, home=str(tmp_path / "h"))


def commands(intent):
    return [s["command"] for s in intent["steps"]]


@pytest.mark.parametrize("text,expected", [
    ("crie a pasta projetos", ["mkdir projetos"]),
    ("Por favor, crie as pastas a, b e c", ["mkdir a", "mkdir b", "mkdir c"]),
    ("faça uma pasta chamada fotos_2026.", ["mkdir fotos_2026"]),
    ("liste os arquivos", ["ls -l"]),
    ("mostre os arquivos da pasta ideias", ["ls -l ideias"]),
    ("mostre o conteúdo da lista.txt", ["cat lista.txt"]),
    ("leia a lista", ["cat lista"]),
    ("baixe https://example.com/a.csv como dados.csv", ["curl -L -o dados.csv https://example.com/a.csv"]),
    ("baixe o arquivo https://example.com/pasta/relatorio.pdf", ["curl -L -o relatorio.pdf https://example.com/pasta/relatorio.pdf"]),
    ("renomeie o relatorio.txt para relatorio_final.txt", ["mv relatorio.txt relatorio_final.txt"]),
    ("renomeie a lista.txt para compras", ["mv lista.txt compras.txt"]),   # the format stays
    ("copie a lista.txt para ideias", ["cp lista.txt ideias"]),             # a folder: no extension added
    ("copie ideias/a.md para ideias/b.md", ["cp ideias/a.md ideias/b.md"]),
])
def test_a_request_that_a_rule_settles(service, text, expected):
    assert commands(by_rule(text, service)) == expected


@pytest.mark.parametrize("text,intent", [
    ("abre o Spotify", {"action": "open_app", "app": "Spotify"}),
    ("abre o chrome", {"action": "open_app", "app": "chrome"}),
    ("abra o arquivo lista.txt", {"action": "open_path", "path": "lista.txt"}),
])
def test_opening_things(service, text, intent):
    assert by_rule(text, service) == intent


@pytest.mark.parametrize("text", [
    "crie a pasta projetos e dentro dela um arquivo notas.txt com olá",   # more than one thing: the model reads it
    "crie um arquivo lista2.txt com leite e pão",
    "abre o site da wikipedia",
    "abre o Photoshop",                                                     # not an installed app: the model / the plan will say so
    "baixe https://example.com/ como arquivo",                             # no usable name
    "mostre os arquivos e depois apague um",
    "o que é uma pasta?",
    "crie a pasta meus documentos importantes",                            # a name with spaces: not guessed
])
def test_what_no_rule_settles_goes_to_the_model(service, text):
    assert by_rule(text, service) is None


async def test_a_rule_request_never_calls_the_model(service):
    from chakmati.features.computer.assistant import ComputerAssistant

    class Boom:
        async def chat(self, messages):
            raise AssertionError("the model should not be asked")
    assistant = ComputerAssistant(Boom(), service)
    assert "[[action:" in await assistant.handle("copie a lista.txt para lista_2.txt")
    assert "Listar os arquivos" in await assistant.handle("liste os arquivos")
