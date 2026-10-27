import pytest

from chakmati.computer.describe import friendly, plain_error


@pytest.mark.parametrize("argv,text", [
    (["mkdir", "projetos"], "Criar a pasta projetos"),
    (["mkdir", "-p", "a", "b"], "Criar as pastas a, b"),
    (["touch", "x.txt"], "Criar o arquivo x.txt"),
    (["cp", "a.txt", "b.txt"], "Copiar o arquivo a.txt para b.txt"),
    (["cp", "-r", "fotos", "backup"], "Copiar a pasta fotos para backup"),
    (["mv", "a.txt", "b.txt"], "Renomear a.txt para b.txt"),
    (["mv", "a.txt", "pasta/a.txt"], "Mover a.txt para pasta/a.txt"),
    (["ls", "-l"], "Listar os arquivos"),
    (["ls", "-l", "."], "Listar os arquivos"),
    (["ls", "ideias"], "Listar os arquivos de ideias"),
    (["cat", "lista.txt"], "Mostrar o conteúdo de lista.txt"),
    (["head", "-n", "5", "lista.txt"], "Mostrar o começo de lista.txt"),
    (["grep", "-n", "leite", "lista.txt"], "Procurar “leite” em lista.txt"),
    (["curl", "-L", "-o", "dados.csv", "https://example.com/a/b.csv"], "Baixar de example.com e salvar como dados.csv"),
    (["python3", "ola.py"], "Rodar o script ola.py"),
    (["pwd"], "Mostrar a pasta atual"),
    (["estranho", "x"], "estranho x"),
])
def test_a_command_in_plain_words(argv, text):
    assert friendly(argv) == text


def test_paths_inside_the_workspace_are_shown_relative(tmp_path):
    assert friendly(["cp", str(tmp_path / "a.txt"), str(tmp_path / "pasta" / "b.txt")], tmp_path) == "Copiar o arquivo a.txt para pasta/b.txt"


@pytest.mark.parametrize("message,contains", [
    ("cp (origem): não existe", "Não encontrei esse arquivo ou pasta"),
    ("mv (destino): já existe (não sobrescrevo)", "Já existe um item com esse nome"),
    ("lixeira: só posso escrever em a pasta de trabalho", "Só mexo em itens da pasta de trabalho"),
    ("o comando \"rm\" não está na lista de comandos permitidos", "não sei fazer por aqui"),
    ("não faço isso (apagar arquivos)", "mandar para a lixeira"),
    ("cp: não mudo o formato do arquivo (a extensão tem que continuar .txt)", "mesmo formato"),
    ("cp: a pasta de destino não existe", "crie a pasta primeiro"),
    ("uma frase qualquer que já é clara", "uma frase qualquer que já é clara."),
])
def test_a_refusal_becomes_a_sentence_that_says_what_to_do(message, contains):
    assert contains in plain_error(message)
