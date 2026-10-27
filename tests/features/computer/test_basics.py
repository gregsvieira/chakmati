import json
import os
import sys
from pathlib import Path

import pytest

from chakmati.shared.approvals import ActionStore
from chakmati.features.computer.assistant import ComputerAssistant, parse_intent
from chakmati.features.computer.safety import ComputerError, check_url, find_app, resolve_new_file
from chakmati.features.computer.service import ComputerService

APPS = {"safari": "Safari", "google chrome": "Google Chrome", "spotify": "Spotify", "calendar": "Calendar", "calculator": "Calculator"}


# ----------------------------------------------------------------------------- paths
def test_new_files_stay_inside_the_workspace(tmp_path):
    ok = resolve_new_file(tmp_path, "lista.txt")
    assert ok == (tmp_path / "lista.txt").resolve()
    assert resolve_new_file(tmp_path, "notas/ideias.md").name == "ideias.md"
    assert resolve_new_file(tmp_path, str(tmp_path / "x.txt")) == (tmp_path / "x.txt").resolve()  # absolute but inside


@pytest.mark.parametrize("name", [
    "../fora.txt", "a/../../fora.txt", "/etc/passwd.txt", "~/fora.txt", ".bashrc.txt", "pasta/.oculto.txt", "script.sh", "app.command", "x.plist",
    "semextensao", "", "   ", "a" * 300 + ".txt", "con\x00.txt", "a/b/c/d/e/f.txt", "nome:ruim.txt", "arquivo.TXT.exe",
])
def test_unsafe_names_are_refused(tmp_path, name):
    with pytest.raises(ComputerError):
        resolve_new_file(tmp_path, name)


def test_a_symlink_cannot_lead_out_of_the_workspace(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    (work / "link").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ComputerError):
        resolve_new_file(work, "link/x.txt")


@pytest.mark.parametrize("url", ["file:///etc/passwd", "javascript:alert(1)", "ftp://x.com", "https://user:pw@x.com", "x.com", "", "http://"])
def test_only_plain_web_addresses_open(url):
    with pytest.raises(ComputerError):
        check_url(url)
    assert check_url("https://g1.globo.com/") == "https://g1.globo.com/"


def test_apps_are_found_by_name_or_reported_ambiguous():
    assert find_app("spotify", APPS) == ("Spotify", [])
    assert find_app("o Chrome", {**APPS})[0] == "Google Chrome" or find_app("chrome", APPS) == ("Google Chrome", [])
    assert find_app("cal", APPS)[0] is None and set(find_app("cal", APPS)[1]) == {"Calendar", "Calculator"}
    assert find_app("photoshop", APPS) == (None, [])
    assert find_app("", APPS) == (None, [])


# ----------------------------------------------------------------------------- service
def make(tmp_path, opened=None):
    log = opened if opened is not None else []
    return ComputerService(str(tmp_path / "work"), ActionStore(":memory:"), opener=log.append, apps=lambda: APPS), log


def test_a_file_is_only_written_after_approval_and_the_preview_shows_the_text(tmp_path):
    service, _ = make(tmp_path)
    action, ran = service.propose_create_file("lista.txt", "leite\npão\novos")
    target = tmp_path / "work" / "lista.txt"
    assert not target.exists() and str(target.resolve()) in action.summary and "pão" in action.summary
    done = service.approve(action.id)
    assert done.status == "executed" and target.read_text() == "leite\npão\novos"
    assert not list((tmp_path / "work").glob(".*chakmati-tmp"))


def test_a_rejected_file_is_never_written(tmp_path):
    service, _ = make(tmp_path)
    action, _ = service.propose_create_file("lista.txt", "x")
    service.reject(action.id)
    assert not (tmp_path / "work" / "lista.txt").exists()


def test_an_existing_file_is_never_replaced_by_create(tmp_path):
    service, _ = make(tmp_path)
    service.approve(service.propose_create_file("a.txt", "um")[0].id)
    with pytest.raises(ComputerError, match="já existe"):
        service.propose_create_file("a.txt", "dois")
    assert (tmp_path / "work" / "a.txt").read_text() == "um"


def test_the_file_appearing_between_proposal_and_approval_is_not_overwritten(tmp_path):
    service, _ = make(tmp_path)
    action, _ = service.propose_create_file("b.txt", "novo")
    (tmp_path / "work").mkdir(exist_ok=True)
    (tmp_path / "work" / "b.txt").write_text("do usuário")
    assert service.approve(action.id).status == "failed"
    assert (tmp_path / "work" / "b.txt").read_text() == "do usuário"


def test_a_tampered_proposal_cannot_write_outside(tmp_path):
    service, _ = make(tmp_path)
    action, _ = service.propose_create_file("c.txt", "x")
    service._actions._db.execute("UPDATE actions SET payload = ? WHERE id = ?", (json.dumps({"path": "/tmp/pwned.txt", "content": "x", "overwrite": False}), action.id))
    service._actions._db.commit()
    assert service.approve(action.id).status == "failed" and not Path("/tmp/pwned.txt").exists()


def test_oversized_or_binary_content_is_refused(tmp_path):
    service, _ = make(tmp_path)
    with pytest.raises(ComputerError):
        service.propose_create_file("d.txt", "x" * 200_000)
    with pytest.raises(ComputerError):
        service.propose_create_file("d.txt", "a\x00b")


@pytest.mark.skipif(sys.platform != "darwin", reason="opening apps is macOS-only")
def test_apps_are_opened_only_after_approval_by_exact_name_with_no_shell(tmp_path):
    service, log = make(tmp_path)
    action = service.propose_open_app("spotify")
    assert log == [] and "Spotify" in action.summary  # nothing launched yet
    assert service.approve(action.id).status == "executed" and log == [["open", "-a", "Spotify"]]
    with pytest.raises(ComputerError, match="não encontrei"):
        service.propose_open_app("rm -rf /")
    with pytest.raises(ComputerError, match="qual destes"):
        service.propose_open_app("cal")


def test_urls_open_right_away_but_only_when_safe_and_items_ask_first(tmp_path):
    service, log = make(tmp_path)
    service.open_url("https://g1.globo.com")
    assert log[-1][-1] == "https://g1.globo.com"
    with pytest.raises(ComputerError):
        service.open_url("file:///etc/passwd")
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "a.txt").write_text("x")
    log.clear()
    action = service.propose_open_path(str(tmp_path / "work" / "a.txt"))
    assert log == []
    service.approve(action.id)
    assert log and log[0][0] == "open"
    for bad in ("/etc/hosts", "~/.ssh/id_rsa", str(tmp_path / "work" / "nao-existe.txt")):
        with pytest.raises(ComputerError):
            service.propose_open_path(bad)


# ----------------------------------------------------------------------------- assistant
class LLM:
    def __init__(self, reply):
        self.reply = reply

    async def chat(self, messages):
        return json.dumps(self.reply) if isinstance(self.reply, dict) else self.reply


async def test_assistant_proposes_a_file_and_asks_for_confirmation(tmp_path):
    service, _ = make(tmp_path)
    bot = ComputerAssistant(LLM({"action": "steps", "steps": [{"type": "create_file", "path": "lista.txt", "content": "leite"}]}), service)
    out = await bot.handle("crie um arquivo lista.txt com leite")
    assert "Confirma?" in out and "[[action:" in out and not (tmp_path / "work" / "lista.txt").exists()


async def test_assistant_explains_refusals_and_help(tmp_path):
    service, _ = make(tmp_path)
    out = await ComputerAssistant(LLM({"action": "steps", "steps": [{"type": "create_file", "path": "../x.txt", "content": "x"}]}), service).handle("crie")
    assert out.startswith("Não consegui")
    assert "Não entendi" in await ComputerAssistant(LLM({"action": "other"}), service).handle("blá")
    assert "Não entendi" in await ComputerAssistant(LLM("sem json"), service).handle("blá")
    assert parse_intent('{"action":"format_disk"}') == {"action": "other"}


async def test_assistant_opens_a_site(tmp_path):
    service, log = make(tmp_path)
    out = await ComputerAssistant(LLM({"action": "open_url", "url": "https://g1.globo.com"}), service).handle("abre o g1")
    assert out.startswith("Abri") and log
    assert (await ComputerAssistant(LLM({"action": "open_url", "url": "file:///etc/passwd"}), service).handle("x")).startswith("Não consegui")


# ----------------------------------------------------------------------------- the engine
async def test_the_engine_routes_a_file_request_and_a_spoken_yes_creates_it(tmp_path):
    from chakmati.app.engine import Engine
    from chakmati.shared.gate.base import GateResult, Route
    from chakmati.shared.jobs import JobStore

    class Gate:
        def classify(self, text):
            return GateResult(Route.COMPUTER, 1.0, "fake")

    service, _ = make(tmp_path)
    engine = Engine(Gate(), LLM("x"), JobStore(":memory:"), computer_service=service,
                    computer_assistant=ComputerAssistant(LLM({"action": "steps", "steps": [{"type": "create_file", "path": "lista.txt", "content": "leite"}]}), service))
    reply = await engine.handle("crie um arquivo lista.txt com leite")
    out = await engine.run_job(engine._store.get(reply.job_id))
    assert "Confirma?" in out and engine.awake and not (tmp_path / "work" / "lista.txt").exists()
    assert (await engine.handle("sim")).text.startswith("Arquivo criado")
    assert (tmp_path / "work" / "lista.txt").read_text() == "leite"


async def test_with_nothing_wired_the_route_says_it_is_off():
    from chakmati.app.engine import Engine
    from chakmati.shared.gate.base import GateResult, Route
    from chakmati.shared.jobs import JobStore

    class Gate:
        def classify(self, text):
            return GateResult(Route.COMPUTER, 1.0, "fake")

    engine = Engine(Gate(), LLM("x"), JobStore(":memory:"))
    reply = await engine.handle("abre o Spotify")
    assert "desativadas" in await engine.run_job(engine._store.get(reply.job_id))
