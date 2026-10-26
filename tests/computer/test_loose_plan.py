"""Loose requests ("copie a lista", "mande o rascunho para a lixeira"): the plan comes from what the model already returned, is checked against the
disk and the policy before it is shown, and a request that does not say enough becomes a question."""

import pytest

from liteagent.approvals import ActionStore
from liteagent.computer.assistant import ComputerAssistant
from liteagent.computer.service import ComputerService


class LLM:
    def __init__(self, *replies):
        self.replies, self.prompts = list(replies), []

    async def chat(self, messages):
        self.prompts.append(messages)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def make(tmp_path, *replies, apps=None):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    service = ComputerService(str(ws), ActionStore(":memory:"), opener=lambda a: None, apps=lambda: apps or {"safari": "Safari", "spotify": "Spotify"}, home=str(tmp_path / "home"))
    llm = LLM(*replies)
    return ComputerAssistant(llm, service), service, llm, ws


STEPS = '{"action":"steps","steps":[{"type":"create_file","path":"a.txt","content":"oi"},{"type":"command","command":"cp a.txt b.txt"}]}'


async def test_the_plan_is_the_model_s_steps_in_plain_lines_and_the_model_is_asked_only_once(tmp_path):
    assistant, service, llm, ws = make(tmp_path, STEPS)
    lines = await assistant.plan("crie a.txt com oi e copie para b.txt")
    assert lines == ["1. Criar o arquivo a.txt  [seguro]", "2. cp a.txt b.txt  [seguro]"]
    answer = await assistant.handle("crie a.txt com oi e copie para b.txt")
    assert "Plano (2 passos)" in answer and "[[action:" in answer
    assert len(llm.prompts) == 1  # the answer reused what the plan had asked


async def test_a_step_that_uses_what_an_earlier_step_makes_is_not_refused(tmp_path):
    assistant, *_ = make(tmp_path, '{"action":"steps","steps":[{"type":"command","command":"mkdir docs"},{"type":"command","command":"touch docs/n.txt"},{"type":"command","command":"cp docs/n.txt docs/m.txt"}]}')
    lines = await assistant.plan("faça a pasta docs com n.txt e uma cópia m.txt")
    assert len(lines) == 3 and not any("⚠" in line for line in lines)


async def test_a_problem_shows_in_the_plan_before_anything_is_approved(tmp_path):
    assistant, service, llm, ws = make(tmp_path, '{"action":"steps","steps":[{"type":"command","command":"mkdir docs"},{"type":"command","command":"cp falta.txt docs/falta.txt"}]}')
    lines = await assistant.plan("quero que você copie falta.txt para docs")
    assert lines[0].startswith("1. mkdir docs") and "⚠ cp (origem): não existe" in lines[1]
    answer = await assistant.handle("quero que você copie falta.txt para docs")
    assert answer.startswith("Não consegui") and service.pending() == []


async def test_a_name_without_extension_is_found(tmp_path):
    assistant, service, llm, ws = make(tmp_path, '{"action":"trash","path":"rascunho"}')
    (ws / "rascunho.txt").write_text("x")
    lines = await assistant.plan("mande o rascunho para a lixeira")
    assert lines == ["Mover rascunho.txt para a lixeira (dá para recuperar)"]
    answer = await assistant.handle("mande o rascunho para a lixeira")
    assert "rascunho.txt" in answer and "[[action:" in answer


async def test_a_name_that_fits_two_files_becomes_a_question(tmp_path):
    assistant, service, llm, ws = make(tmp_path, '{"action":"trash","path":"rascunho"}')
    (ws / "rascunho.txt").write_text("x")
    (ws / "ideias").mkdir()
    (ws / "ideias" / "Rascunho.md").write_text("y")
    assert await assistant.plan("mande o rascunho para a lixeira") is None
    answer = await assistant.handle("mande o rascunho para a lixeira")
    assert answer.startswith("Qual destes?") and "rascunho.txt" in answer and "ideias/Rascunho.md" in answer and service.pending() == []


@pytest.mark.parametrize("reply,question", [
    ('{"action":"trash"}', "Qual arquivo ou pasta?"),
    ('{"action":"open_app"}', "Qual aplicativo"),
    ('{"action":"open_url"}', "Qual site"),
])
async def test_a_request_that_does_not_say_what_on_becomes_a_question(tmp_path, reply, question):
    assistant, service, *_ = make(tmp_path, reply)
    assert question in await assistant.handle("faz isso aí")
    assert service.pending() == []


async def test_an_app_that_is_not_installed_is_a_problem_in_the_plan(tmp_path):
    assistant, *_ = make(tmp_path, '{"action":"open_app","app":"Photoshop"}')
    import sys
    if sys.platform != "darwin":
        pytest.skip("opening apps is macOS only")
    lines = await assistant.plan("abre o Photoshop")
    assert lines == ["Abrir o aplicativo Photoshop  ⚠ não encontrei esse aplicativo instalado"]


async def test_an_app_name_that_fits_two_asks_which(tmp_path):
    import sys
    if sys.platform != "darwin":
        pytest.skip("opening apps is macOS only")
    assistant, *_ = make(tmp_path, '{"action":"open_app","app":"safar"}', apps={"safari": "Safari", "safari technology preview": "Safari Technology Preview", "spotify": "Spotify"})
    answer = await assistant.handle("abre o safar")
    assert answer.startswith("Qual destes aplicativos?") and "Safari" in answer


async def test_editing_a_file_that_does_not_exist_shows_the_problem(tmp_path):
    assistant, service, llm, ws = make(tmp_path, '{"action":"edit","path":"nada.txt","instruction":"x"}')
    lines = await assistant.plan("edite o nada.txt")
    assert len(lines) == 1 and lines[0].startswith("Editar nada.txt") and "⚠" in lines[0]


async def test_a_request_the_model_cannot_read_has_no_plan(tmp_path):
    assistant, *_ = make(tmp_path, "não sei")
    assert await assistant.plan("blá blá") is None


async def test_moving_into_a_folder_keeps_the_file_name(tmp_path):
    assistant, service, llm, ws = make(tmp_path, '{"action":"steps","steps":[{"type":"command","command":"mkdir arquivos"},{"type":"command","command":"mv lista.txt arquivos"}]}')
    (ws / "lista.txt").write_text("x")
    lines = await assistant.plan("crie a pasta arquivos e mova a lista.txt para lá")
    assert len(lines) == 2 and not any("⚠" in l for l in lines) and lines[1].endswith("arquivos/lista.txt  [seguro]")


async def test_when_the_model_cannot_read_a_trash_request_the_words_still_do(tmp_path):
    assistant, service, llm, ws = make(tmp_path, "não sei")
    (ws / "lista.txt").write_text("x")
    answer = await assistant.handle("mande a lista para a lixeira")
    assert "lista.txt" in answer and "[[action:" in answer


async def test_a_file_verb_with_no_file_is_a_question_not_the_general_help(tmp_path):
    assistant, service, llm, ws = make(tmp_path, "não sei")
    assert (await assistant.handle("edite o arquivo")).startswith("Qual arquivo ou pasta")
    assert (await assistant.handle("bom dia")).startswith("Não entendi")  # nothing about files: the usual help


async def test_apague_tudo_is_never_done_and_never_guessed_by_the_model(tmp_path):
    assistant, service, llm, ws = make(tmp_path, '{"action":"steps","steps":[{"type":"command","command":"ls"}]}')
    answer = await assistant.handle("apague tudo")
    assert answer.startswith("Não apago nem mando tudo") and service.pending() == [] and llm.prompts == []


async def test_a_trash_request_does_not_need_the_model(tmp_path):
    assistant, service, llm, ws = make(tmp_path, "não sei")
    (ws / "lista.txt").write_text("x")
    assert "lista.txt" in await assistant.handle("mande a lista para a lixeira") and llm.prompts == []


async def test_two_files_with_that_name_ask_which_even_when_the_model_would_guess(tmp_path):
    assistant, service, llm, ws = make(tmp_path, '{"action":"steps","steps":[{"type":"command","command":"date"}]}')
    (ws / "rascunho.txt").write_text("x")
    (ws / "ideias").mkdir()
    (ws / "ideias" / "Rascunho.md").write_text("y")
    assert (await assistant.handle("mande o rascunho para a lixeira")).startswith("Qual destes?")


async def test_a_copy_of_a_file_is_named_by_rule(tmp_path):
    assistant, service, llm, ws = make(tmp_path, "não sei")
    (ws / "relatorio.txt").write_text("x")
    lines = await assistant.plan("faça uma cópia do relatório")
    assert lines is None  # one step: no list
    answer = await assistant.handle("faça uma cópia do relatório")
    assert "relatorio_copia.txt" in answer and "[[action:" in answer


async def test_delete_with_a_file_name_goes_to_the_trash_plan_and_says_if_it_is_not_there(tmp_path):
    assistant, *_ = make(tmp_path, "não sei")
    lines = await assistant.plan("apague o arquivo naoexiste.txt")
    assert len(lines) == 1 and lines[0].startswith("Mover naoexiste.txt para a lixeira") and "⚠" in lines[0]


# ------------------------------------------------------------------------------------------------ names inside commands
async def test_a_name_without_extension_inside_a_command_is_found(tmp_path):
    assistant, service, llm, ws = make(tmp_path, '{"action":"steps","steps":[{"type":"command","command":"cat lista"}]}')
    (ws / "lista.txt").write_text("leite")
    assert await assistant.plan("quero ver o que tem na lista") is None
    answer = await assistant.handle("quero ver o que tem na lista")
    assert "lista.txt" in answer and "Não consegui" not in answer and len(llm.prompts) == 1


async def test_the_wrong_case_and_a_missing_folder_in_a_command_are_fixed(tmp_path):
    assistant, service, llm, ws = make(tmp_path, '{"action":"steps","steps":[{"type":"command","command":"cp rascunho.md copia.md"}]}')
    (ws / "ideias").mkdir()
    (ws / "ideias" / "Rascunho.md").write_text("x")
    answer = await assistant.handle("copie o rascunho.md para copia.md")
    assert "ideias/Rascunho.md" in answer and "[[action:" in answer  # (and where it writes was left alone)


async def test_a_command_name_that_fits_two_files_asks(tmp_path):
    assistant, service, llm, ws = make(tmp_path, '{"action":"steps","steps":[{"type":"command","command":"cat rascunho"}]}')
    (ws / "rascunho.txt").write_text("x")
    (ws / "rascunho.md").write_text("y")
    answer = await assistant.handle("quero ver o que tem no rascunho")
    assert answer.startswith("Qual destes?") and "rascunho.txt" in answer and "rascunho.md" in answer and service.pending() == []


def test_fix_names_only_touches_what_a_command_reads(tmp_path):
    _, service, _, ws = make(tmp_path, "x")
    (ws / "lista.txt").write_text("x")
    assert service.fix_names("cp lista nova.txt")[0] == "cp lista.txt nova.txt"      # the source is fixed, the new name is left as it is
    assert service.fix_names("mkdir lista")[0] == "mkdir lista"                        # not a command that reads names
    assert service.fix_names("grep leite lista")[0] == "grep leite lista.txt"          # the first word is the pattern, not a file
    assert service.fix_names("head -n 5 lista")[0] == "head -n 5 lista.txt"
    assert service.fix_names("cat naoexiste")[0] == "cat naoexiste"                    # nothing found: the usual error will say so


@pytest.mark.parametrize("text", ["edite o arquivo", "abra esse arquivo", "apague a pasta", "copie um arquivo"])
async def test_a_file_verb_with_no_name_asks_without_calling_the_model(tmp_path, text):
    assistant, service, llm, ws = make(tmp_path, '{"action":"open_path","path":"qualquer"}')
    assert (await assistant.handle(text)).startswith("Qual arquivo ou pasta") and llm.prompts == []


async def test_a_name_the_model_forgot_is_taken_from_the_request(tmp_path):
    assistant, service, llm, ws = make(tmp_path, '{"action":"trash"}')
    (ws / "velho.txt").write_text("x")
    answer = await assistant.handle("quero me livrar do velho.txt")
    assert "velho.txt" in answer and "[[action:" in answer
