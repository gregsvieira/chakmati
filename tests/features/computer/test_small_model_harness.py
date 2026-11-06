"""What surrounds a small model so it errs less: a typed menu of steps, a reply shaped by a schema, a second try that says why, and a request in
several parts read one part at a time."""

import json

import pytest

from chakmati.shared.approvals import ActionStore
from chakmati.shared.llm import is_small_model
from chakmati.features.computer import rules
from chakmati.features.computer.assistant import INTENT_SCHEMA, SYSTEM_COMPACT, ComputerAssistant, diagnose, parse_intent
from chakmati.features.computer.service import ComputerService


class LLM:
    supports_schema = True

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    async def chat(self, messages, schema=None):
        self.calls.append((list(messages), schema))
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def make(tmp_path, *replies, compact=False):
    ws = tmp_path / "ws"
    ws.mkdir(exist_ok=True)
    service = ComputerService(str(ws), ActionStore(":memory:"), opener=lambda a: None, apps=lambda: {"spotify": "Spotify"}, home=str(tmp_path / "home"))
    llm = LLM(*replies)
    return ComputerAssistant(llm, service, compact=compact), service, llm, ws


def steps(*items):
    return json.dumps({"action": "steps", "steps": list(items)})


# --- typed steps ---------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("step,command", [
    ({"type": "mkdir", "path": "fotos"}, "mkdir -p fotos"),
    ({"type": "copy", "source": "a.txt", "destination": "b.txt"}, "cp a.txt b.txt"),
    ({"type": "move", "source": "a.txt", "destination": "b.txt"}, "mv a.txt b.txt"),
    ({"type": "list"}, "ls -la"),
    ({"type": "list", "path": "docs"}, "ls -la docs"),
    ({"type": "show", "path": "a.txt"}, "cat a.txt"),
    ({"type": "mkdir", "path": "minha pasta"}, "mkdir -p 'minha pasta'"),  # a name with a space stays one word
])
def test_a_typed_step_becomes_the_command_code_spells(step, command):
    assert parse_intent(steps(step)) == {"action": "steps", "steps": [{"type": "command", "command": command}]}


@pytest.mark.parametrize("step", [{"type": "copy", "source": "a.txt"}, {"type": "mkdir"}, {"type": "show", "path": "  "}])
def test_a_typed_step_missing_a_field_is_dropped_not_guessed(step):
    out = parse_intent(steps(step))
    assert out["action"] == "other" or not out.get("steps")


async def test_a_create_file_step_without_content_is_an_empty_file_not_a_crash(tmp_path):
    assistant, *_ = make(tmp_path, steps({"type": "create_file", "path": "vazio.txt"}, {"type": "mkdir", "path": "docs"}))
    lines = await assistant.plan("quero um arquivo vazio chamado vazio.txt e uma pasta docs")
    assert lines[0].startswith("1. Criar o arquivo vazio.txt") and not any("⚠" in line for line in lines)


def test_a_typed_step_cannot_smuggle_a_shell_operator():
    out = parse_intent(steps({"type": "mkdir", "path": "x; rm -rf ~"}))
    assert out["steps"][0]["command"] == "mkdir -p 'x; rm -rf ~'"  # one quoted word: policy.py refuses it as a name


def test_the_schema_only_allows_known_actions_and_step_types():
    assert "format_disk" not in INTENT_SCHEMA["properties"]["action"]["enum"]
    assert {"mkdir", "copy", "command", "create_file"} <= set(INTENT_SCHEMA["properties"]["steps"]["items"]["properties"]["type"]["enum"])


# --- the schema reaches the model --------------------------------------------------------------------------------------------------
async def test_the_intent_schema_is_sent_with_the_request(tmp_path):
    assistant, _, llm, _ = make(tmp_path, steps({"type": "mkdir", "path": "fotos"}))
    await assistant.plan("quero uma pasta para as fotos da viagem de ontem")
    assert llm.calls[0][1] == INTENT_SCHEMA


# --- second chance, with the reason -----------------------------------------------------------------------------------------------------
def test_diagnose_names_what_was_wrong():
    assert "not a JSON" in diagnose("claro!")
    assert "not valid" in diagnose('{"action": }')
    assert "no usable steps" in diagnose('{"action":"steps","steps":[]}')
    assert "must be one of" in diagnose('{"action":"format_disk"}')


async def test_a_reply_with_nothing_to_do_is_asked_again_with_the_reason(tmp_path):
    assistant, _, llm, _ = make(tmp_path, "claro, vou fazer isso", steps({"type": "mkdir", "path": "fotos"}))
    await assistant.plan("quero uma pasta para as fotos da viagem de ontem")
    assert len(llm.calls) == 2
    second = llm.calls[1][0]
    assert second[-2] == {"role": "assistant", "content": "claro, vou fazer isso"} and "not a JSON object" in second[-1]["content"]
    assert (await assistant._intent("quero uma pasta para as fotos da viagem de ontem"))["steps"]


async def test_a_step_policy_refused_for_how_it_is_written_is_fixed_once(tmp_path):
    assistant, _, llm, _ = make(tmp_path,
        steps({"type": "command", "command": "mkdir fotos && ls"}),
        steps({"type": "command", "command": "mkdir fotos"}, {"type": "command", "command": "ls fotos"}))
    lines = await assistant.plan("quero uma pasta para as fotos da viagem e ver o que tem nela")
    assert len(llm.calls) == 2 and "refused" in llm.calls[1][0][-1]["content"] and "encadeamento" in llm.calls[1][0][-1]["content"]
    assert lines and not any("⚠" in line for line in lines)


async def test_a_step_policy_refused_for_what_is_on_the_disk_is_not_retried(tmp_path):
    assistant, _, llm, _ = make(tmp_path, steps({"type": "command", "command": "cp falta.txt b.txt"}))
    lines = await assistant.plan("quero uma cópia do arquivo falta para b.txt agora mesmo")
    assert len(llm.calls) == 1 and "⚠" in lines[0]  # the person must hear it, the model cannot invent the file


async def test_a_failed_fix_keeps_the_first_reading(tmp_path):
    assistant, *_ = make(tmp_path, steps({"type": "command", "command": "mkdir fotos && ls"}), "não sei")
    lines = await assistant.plan("quero uma pasta para as fotos da viagem e ver o que tem nela")
    assert lines and "⚠" in lines[0]


# --- small models --------------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("name,small", [
    ("qwen3.5:0.8b", True), ("qwen3.5:4b", True), ("granite4:3b", True), ("granite4:micro", True), ("lfm3", True), ("lfm3:1.7b", True),
    ("qwen3.5:latest", False), ("qwen3.5:9b", False), ("deepseek-r1:14b", False), ("llama3:70b", False),
])
def test_which_chat_models_count_as_small(name, small):
    assert is_small_model(name) is small


@pytest.mark.parametrize("text,parts", [
    ("crie a pasta x e depois copie a.txt para x/b.txt", ["crie a pasta x", "copie a.txt para x/b.txt"]),
    ("crie a pasta x, depois a pasta y, então a pasta z", ["crie a pasta x", "a pasta y", "a pasta z"]),
    ("crie a pasta x; liste os arquivos", ["crie a pasta x", "liste os arquivos"]),
    ("crie as pastas a e b", ["crie as pastas a e b"]),  # a plain "e" never splits
    ("crie a pasta x", ["crie a pasta x"]),
])
def test_split_compound(text, parts):
    assert rules.split_compound(text) == parts


async def test_a_compact_assistant_reads_each_part_alone_and_joins_the_steps(tmp_path):
    assistant, _, llm, ws = make(tmp_path, steps({"type": "copy", "source": "a.txt", "destination": "docs/b.txt"}), compact=True)
    (ws / "a.txt").write_text("oi")
    intent = await assistant._parse("faça uma pasta docs e depois ponha uma cópia de a.txt lá dentro como b.txt")
    assert [s["command"] for s in intent["steps"]] == ["mkdir docs", "cp a.txt docs/b.txt"]  # the first part is a rule's, the second the model's
    assert len(llm.calls) == 1 and llm.calls[0][0][0]["content"] == SYSTEM_COMPACT


async def test_a_part_that_is_not_steps_sends_the_whole_request_to_the_model(tmp_path):
    whole = steps({"type": "mkdir", "path": "docs"}, {"type": "mkdir", "path": "docs2"})
    assistant, _, llm, _ = make(tmp_path, whole, compact=True)
    intent = await assistant._parse("abra o Spotify e depois faça as pastas docs e docs2 para a música")
    assert len(llm.calls) == 1 and [s["command"] for s in intent["steps"]] == ["mkdir -p docs", "mkdir -p docs2"]  # "abre o Spotify" is a rule's open_app: not steps, so no split


async def test_a_big_model_is_never_split(tmp_path):
    assistant, _, llm, _ = make(tmp_path, steps({"type": "mkdir", "path": "docs"}, {"type": "mkdir", "path": "docs2"}))
    await assistant._parse("faça uma pasta docs e depois uma pasta docs2 para a música")
    assert len(llm.calls) == 1
