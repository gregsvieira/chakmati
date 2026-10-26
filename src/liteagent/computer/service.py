"""Acting on the computer, always through the person's approval.

  * every command, file creation, edit, move to the trash, revert and program launch is a PROPOSAL the person approves
    (the exact command or path is shown); only "safe" commands can be kept approved ("manter aprovado"), and running a script,
    downloading, opening a program, editing, trashing and reverting ask every single time, whatever that setting says;
  * the policy (policy.py) is checked when a command is proposed and AGAIN right before it runs;
  * a command's output is redacted, truncated and shown to the person; it is never given back to the model, so nothing a
    command prints can steer the agent;
  * nothing is deleted: removal means "move to the trash"; editing keeps the original as backup_<name> and can be reverted.
"""

import difflib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from ..approvals import Action, ActionStore, ApprovalService
from .policy import is_dir_in, DOWNLOAD, EXECUTABLE_EXT, RUN, SAFE, Checked, PolicyError, Roots, check, clean_env, resolve
from . import documents, grading
from .safety import ComputerError, check_content, check_url, find_app, installed_apps, plain, resolve_new_file
from .secrets import has_secret, looks_secret, redact

MAX_OUTPUT = 4000
MAX_EDIT_BYTES = 100_000
EDITABLE_EXT = {".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".html", ".css", ".js", ".ts", ".py", ".sql", ".xml", ".log", ".ini", ".toml", ".tex", ".srt"}


def system_open(argv: list[str]) -> None:
    subprocess.run(argv, check=True, timeout=15, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def run_argv(argv: list[str], cwd: str, timeout: int) -> tuple[int, bytes]:
    """Starts the program directly (never through a shell), with a clean environment, no input, and a time limit."""
    try:
        done = subprocess.run(argv, cwd=cwd, env=clean_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    except subprocess.TimeoutExpired:
        return 124, b"(tempo esgotado: o comando foi interrompido)"
    except OSError as exc:
        return 127, f"(não consegui iniciar o programa: {exc})".encode()
    return done.returncode, done.stdout[:200_000]


def trash_with_finder(path: Path) -> None:
    """Moves to the Trash through Finder, so "Put Back" works. Nothing is ever deleted."""
    if sys.platform != "darwin":
        raise ComputerError("a lixeira só funciona no macOS por enquanto")
    text = str(path)
    if any(c in text for c in '"\\\n\r'):
        raise ComputerError("o nome do item tem caracteres que não consigo passar com segurança para a lixeira")
    subprocess.run(["osascript", "-e", f'tell application "Finder" to delete POSIX file "{text}"'], check=True, timeout=30,
                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class ComputerService(ApprovalService):
    prefix = "computer."
    cancel_text = "Certo, não fiz nada no computador."
    PREVIEW_LINES = 12

    def __init__(self, workspace: str, actions: ActionStore, ttl_seconds: float = 900.0, now: Callable[[], float] = time.time,
                 opener: Callable[[list[str]], None] = system_open, apps: Callable[[], dict[str, str]] = installed_apps,
                 runner: Callable[[list[str], str, int], tuple[int, bytes]] = run_argv, trasher: Callable[[Path], None] = trash_with_finder,
                 home: str | None = None):
        super().__init__(actions, ttl_seconds, now)
        self.workspace = Path(os.path.expanduser(workspace))
        self._open, self._apps, self._runner, self._trash = opener, apps, runner, trasher
        self._home = home
        self.standing = False  # "manter aprovado": only ever applies to safe commands and new files in the workspace
        self._lock = actions._lock
        self._db = actions._db
        self._db.executescript(
            """CREATE TABLE IF NOT EXISTS computer_plans (id TEXT PRIMARY KEY, steps TEXT NOT NULL, idx INTEGER NOT NULL, status TEXT NOT NULL);
               CREATE TABLE IF NOT EXISTS computer_edits (id INTEGER PRIMARY KEY AUTOINCREMENT, original TEXT NOT NULL, backup TEXT NOT NULL, at REAL NOT NULL, reverted INTEGER NOT NULL DEFAULT 0);"""
        )
        self._db.commit()

    @property
    def roots(self) -> Roots:
        return Roots.make(self.workspace, self._home)

    def pending_confirmation(self) -> Action | None:
        waiting = self.pending()
        return waiting[-1] if waiting else None

    # ------------------------------------------------------------------------------------------ describing a proposal
    def _risk_text(self, checked: Checked) -> str:
        label = {SAFE: "seguro", RUN: "roda um programa: sempre pede aprovação", DOWNLOAD: "baixa da internet: sempre pede aprovação"}[checked.cls]
        body = f"Executar: {checked.shown}\n({checked.label}; {label})\nVerificado: " + "; ".join(checked.checks)
        if checked.preview is not None:
            lines = checked.preview.read_text(encoding="utf-8", errors="replace").splitlines()
            body += f"\nScript {checked.preview.name} ({len(lines)} linhas):\n" + "\n".join(lines[:40]) + ("\n…" if len(lines) > 40 else "")
        return body

    # ------------------------------------------------------------------------------------------ commands
    def validate(self, command: str, roots: Roots | None = None) -> Checked:
        try:
            return check(command, roots or self.roots)
        except PolicyError as exc:
            raise ComputerError(str(exc)) from None

    def propose_command(self, command: str, plan: dict | None = None) -> tuple[Action | None, str | None]:
        """(proposal, None), or (None, output) when a safe command ran straight away because it was kept approved."""
        checked = self.validate(command)  # first check
        if checked.cls == SAFE and self.standing and plan is None:
            return None, self._run_checked(checked)
        payload = {"command": command, "cls": checked.cls, "auto_ok": checked.cls == SAFE, "risk": checked.cls, "plan": plan}
        return self._propose("computer.cmd", self._risk_text(checked), payload), None

    def _run_checked(self, checked: Checked) -> str:
        self.workspace.mkdir(parents=True, exist_ok=True)  # the working folder is made on first use
        code, out = self._runner(checked.argv, str(self.workspace), checked.timeout)
        text = redact(out.decode("utf-8", "replace")).strip()
        if len(text) > MAX_OUTPUT:
            text = text[:MAX_OUTPUT] + "\n… (saída cortada)"
        if code == 1 and checked.argv[0] == "grep":  # grep exits 1 when nothing matched: that is an answer, not an error
            return "(nenhuma ocorrência)"
        if code != 0:  # a command that failed is reported as failed, never as done
            raise ComputerError((text or "o comando falhou") + f"\n(terminou com código {code})")
        return text or "(sem saída)"

    # ------------------------------------------------------------------------------------------ files
    def propose_create_file(self, relative: str, content: str, overwrite: bool = False, plan: dict | None = None) -> tuple[Action | None, str | None]:
        target = resolve_new_file(self.workspace, relative)
        content = check_content(content)
        if has_secret(content):
            raise ComputerError("o texto parece conter senhas, chaves ou dados pessoais, então não gravo")
        if target.exists():
            raise ComputerError(f"já existe um arquivo {target.name} em {target.parent}; para mudar um arquivo existente peça uma edição (o original fica de backup)")
        if self.standing and plan is None:
            return None, self._write_new(target, content)
        lines = content.splitlines()
        shown = "\n".join(lines[: self.PREVIEW_LINES]) + (f"\n… (+{len(lines) - self.PREVIEW_LINES} linhas)" if len(lines) > self.PREVIEW_LINES else "")
        payload = {"path": str(target), "content": content, "auto_ok": True, "risk": SAFE, "plan": plan}
        return self._propose("computer.create_file", f"Criar o arquivo {target}\n{shown}", payload), None

    def propose_create_document(self, relative: str, kind: str, raw_spec: object) -> Action:
        """A Word/Excel/PowerPoint file. Always asks, even when "manter aprovado" is on: it is a binary file the person cannot read here."""
        if kind not in documents.KINDS:
            raise ComputerError("tipo de documento inválido")
        name = relative.strip()
        if not name.lower().endswith(f".{kind}"):
            name = f"{Path(name).stem or 'documento'}.{kind}"
        target = resolve_new_file(self.workspace, name, {f".{kind}"})
        spec = documents.check_spec(kind, raw_spec)
        if has_secret(json.dumps(spec.data, ensure_ascii=False)):
            raise ComputerError("o texto parece conter senhas, chaves ou dados pessoais, então não gravo")
        if target.exists():
            raise ComputerError(f"já existe um arquivo {target.name} em {target.parent}")
        payload = {"path": str(target), "kind": kind, "spec": spec.data, "auto_ok": False, "risk": "edit"}
        return self._propose("computer.create_document", f"Criar {target} (abre no {documents.KINDS[kind]})\n{documents.preview(spec)}", payload)

    def read_exam_folder(self, folder: str) -> tuple[Path, list, list[str]]:
        """(the folder, the exams read, the files that could not be read) for a folder of exams (PDF with text, scanned PDF, or photo) in the workspace."""
        try:
            target = resolve(folder, self.roots, must_exist=True, what="ler")
        except PolicyError as exc:
            raise ComputerError(str(exc)) from None
        if not target.is_dir():
            raise ComputerError(f"{folder} não é uma pasta")
        exams, unreadable = grading.read_folder(target)
        return target, exams, unreadable

    def _write_document(self, p: dict) -> str:
        target = resolve_new_file(self.workspace, p["path"], {f".{p['kind']}"})  # checked again at the moment of writing
        spec = documents.check_spec(p["kind"], p["spec"])
        if target.exists() or target.is_symlink():
            raise ComputerError("o arquivo passou a existir; nada foi escrito")
        target.parent.mkdir(parents=True, exist_ok=True)
        documents.write(spec, target)
        app = documents.KINDS[p["kind"]]
        try:  # the file is ours and was just written: showing it in the app is part of the job (a failure here is not a failure to write)
            if sys.platform == "darwin" and app in self._apps().values():
                self._open(["open", "-a", app, str(target)])
                return f"Arquivo criado e aberto no {app}: {target}"
        except Exception:
            pass
        return f"Arquivo criado: {target}"

    def _write_new(self, target: Path, content: str) -> str:
        target = resolve_new_file(self.workspace, str(target))  # checked again at the moment of writing
        check_content(content)
        if target.exists() or target.is_symlink():
            raise ComputerError("o arquivo passou a existir; nada foi escrito")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.chakmati-tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, target)
        return f"Arquivo criado: {target}"

    # ------------------------------------------------------------------------------------------ editing with a backup
    def _editable(self, word: str) -> Path:
        try:
            path = resolve(word, self.roots, write=True, editable=True, must_exist=True, what="editar")
        except PolicyError as exc:
            raise ComputerError(str(exc)) from None
        if not path.is_file() or path.suffix.lower() not in EDITABLE_EXT:
            raise ComputerError("só edito arquivos de texto comuns")
        if path.name.startswith("backup_"):
            raise ComputerError("esse já é um backup: use \"reverter\" no arquivo original")
        if path.stat().st_size > MAX_EDIT_BYTES:
            raise ComputerError("arquivo grande demais para editar")
        return path

    def read_for_edit(self, word: str) -> tuple[Path, str]:
        path = self._editable(word)
        text = path.read_text(encoding="utf-8", errors="strict")
        if has_secret(text):
            raise ComputerError("o arquivo parece conter senhas, chaves ou dados pessoais: não carrego o conteúdo")
        return path, text

    def propose_edit(self, word: str, new_content: str) -> Action:
        path, old = self.read_for_edit(word)
        new_content = check_content(new_content)
        if has_secret(new_content):
            raise ComputerError("o novo texto parece conter senhas ou dados pessoais")
        if new_content == old:
            raise ComputerError("não há nada para mudar")
        backup = path.with_name(f"backup_{path.name}")
        if backup.exists():
            raise ComputerError(f"já existe {backup.name}: reverta a edição anterior (ou renomeie esse backup) antes de editar de novo")
        diff = list(difflib.unified_diff(old.splitlines(), new_content.splitlines(), "antes", "depois", lineterm="", n=1))
        shown = "\n".join(diff[:30]) + (f"\n… (+{len(diff) - 30} linhas)" if len(diff) > 30 else "")
        summary = f"Editar {path}\nO original fica como {backup.name} (ao lado) e a versão nova toma o lugar do nome. Dá para reverter.\n{shown}"
        return self._propose("computer.edit", summary, {"path": str(path), "new_content": new_content, "risk": "edit", "auto_ok": False})

    def _do_edit(self, p: dict) -> str:
        path = self._editable(p["path"])  # checked again
        backup = path.with_name(f"backup_{path.name}")
        if backup.exists():
            raise ComputerError(f"{backup.name} passou a existir; nada foi alterado")
        new = check_content(p["new_content"])
        if has_secret(new):
            raise ComputerError("o novo texto parece conter senhas ou dados pessoais")
        os.rename(path, backup)  # the original stays, untouched, as the backup
        try:
            tmp = path.with_name(f".{path.name}.chakmati-tmp")
            tmp.write_text(new, encoding="utf-8")
            shutil.copymode(backup, tmp)
            os.replace(tmp, path)
        except Exception:
            if not path.exists():
                os.rename(backup, path)  # put the original back: a failed edit leaves nothing changed
            raise
        with self._lock:
            self._db.execute("INSERT INTO computer_edits (original, backup, at) VALUES (?,?,?)", (str(path), str(backup), self._now()))
            self._db.commit()
        return f"Editado: {path.name}. O original está em {backup.name}."

    def propose_revert(self, word: str) -> Action:
        path = self._editable(word) if not Path(word).name.startswith("backup_") else None
        if path is None:
            raise ComputerError("diga o nome do arquivo original (sem backup_)")
        with self._lock:
            row = self._db.execute("SELECT id, backup FROM computer_edits WHERE original = ? AND reverted = 0 ORDER BY id DESC LIMIT 1", (str(path),)).fetchone()
        if row is None:
            raise ComputerError("não tenho uma edição minha para reverter nesse arquivo")
        backup = Path(row[1])
        if not backup.is_file():
            raise ComputerError(f"o backup {backup.name} não está mais lá")
        summary = f"Reverter {path.name}\nA versão editada vai para a lixeira e {backup.name} volta a se chamar {path.name}."
        return self._propose("computer.revert", summary, {"path": str(path), "backup": str(backup), "edit_id": row[0], "risk": "edit", "auto_ok": False})

    def _do_revert(self, p: dict) -> str:
        path, backup = Path(p["path"]), Path(p["backup"])
        with self._lock:
            row = self._db.execute("SELECT 1 FROM computer_edits WHERE id = ? AND original = ? AND backup = ? AND reverted = 0", (p["edit_id"], str(path), str(backup))).fetchone()
        if row is None or not backup.is_file() or not path.is_file() or backup.name != f"backup_{path.name}":
            raise ComputerError("a edição não pode mais ser revertida (algo mudou); nada foi feito")
        self._trash(path)  # the edited copy goes to the trash; it is never deleted
        os.rename(backup, path)  # "backup_x.txt" becomes "x.txt" again
        with self._lock:
            self._db.execute("UPDATE computer_edits SET reverted = 1 WHERE id = ?", (p["edit_id"],))
            self._db.commit()
        return f"Revertido: {path.name} voltou à versão anterior (a editada está na lixeira)."

    # ------------------------------------------------------------------------------------------ trash
    def propose_trash(self, word: str) -> Action:
        try:
            path = resolve(word, self.roots, write=True, editable=True, must_exist=True, what="lixeira")
        except PolicyError as exc:
            raise ComputerError(str(exc)) from None
        if path in (self.workspace.resolve(), *self.roots.read_only):
            raise ComputerError("não mando uma pasta inteira de trabalho para a lixeira")
        kind = "a pasta" if path.is_dir() else "o arquivo"
        return self._propose("computer.trash", f"Mover {kind} {path} para a lixeira\n(nada é apagado: dá para recuperar pela lixeira)", {"path": str(path), "risk": "trash", "auto_ok": False})

    def _do_trash(self, p: dict) -> str:
        path = resolve(p["path"], self.roots, write=True, editable=True, must_exist=True, what="lixeira")
        self._trash(path)
        return f"Movido para a lixeira: {path.name}"

    # ------------------------------------------------------------------------------------------ programs and sites
    def propose_open_app(self, name: str) -> Action:
        if sys.platform != "darwin":
            raise ComputerError("abrir aplicativos por aqui só funciona no macOS por enquanto")
        app, candidates = find_app(name, self._apps())
        if app is None:
            raise ComputerError("qual destes? " + ", ".join(candidates) if candidates else f"não encontrei um aplicativo chamado \"{name}\"")
        return self._propose("computer.open_app", f"Abrir o aplicativo {app}", {"app": app, "risk": "run", "auto_ok": False})

    def propose_open_path(self, word: str) -> Action:
        try:
            path = resolve(word, self.roots, must_exist=True, what="abrir")
        except PolicyError as exc:
            raise ComputerError(str(exc)) from None
        if path.suffix.lower() in EXECUTABLE_EXT:
            raise ComputerError("não abro programas executáveis")
        return self._propose("computer.open_path", f"Abrir {path} com o programa padrão", {"path": str(path), "risk": "run", "auto_ok": False})

    def open_url(self, url: str) -> str:
        safe = check_url(url)
        self._open(["open", safe] if sys.platform == "darwin" else ["xdg-open", safe])
        return f"Abri {safe}."

    # ------------------------------------------------------------------------------------------ plans
    def preview_steps(self, steps: list[dict]) -> list[tuple[str, str | None, dict | None]]:
        """Checks every step of a plan WITHOUT proposing anything: (a line for the person, the problem or None, the clean step or None).
        The steps are checked in order against what the earlier ones will have made, so "create a.txt, then copy a.txt" is fine and
        "copy x.txt into a folder that nobody creates" is a problem found now, not after the person has approved."""
        roots = self.roots
        out: list[tuple[str, str | None, dict | None]] = []
        for step in steps:
            try:
                if step.get("type") == "create_file":
                    target = resolve_new_file(self.workspace, step.get("path", ""))
                    check_content(step.get("content", ""))
                    if has_secret(step.get("content", "")) or target.exists() or target in roots.planned:
                        raise ComputerError(f"não posso criar {target.name} (já existe ou o texto tem dados sensíveis)")
                    out.append((f"Criar o arquivo {target.name}  [seguro]", None, {"type": "create_file", "path": str(target), "content": step["content"]}))
                    roots = roots.after([target])
                else:
                    checked = self.validate(step.get("command", ""), roots)
                    tag = {SAFE: "seguro", RUN: "roda programa: pede aprovação", DOWNLOAD: "baixa da internet: pede aprovação"}[checked.cls]
                    out.append((f"{checked.shown.replace(str(self.workspace.resolve()) + os.sep, '')}  [{tag}]", None, {"type": "command", "command": step["command"]}))
                    dirs = checked.writes if checked.argv[0] == "mkdir" else [w for w in checked.writes if any(is_dir_in(r, roots) for r in checked.reads)]
                    roots = roots.after(checked.writes, dirs)
            except ComputerError as exc:
                shown = step.get("command") or step.get("path") or "?"
                out.append((str(shown)[:80], str(exc), None))
                break  # what comes after depends on this step: it cannot be judged
        return out

    def propose_plan(self, goal: str, steps: list[dict]) -> Action:
        """Several steps: the person approves the numbered plan first; each step then still asks for its own approval."""
        if not 2 <= len(steps) <= 12:
            raise ComputerError("um plano tem de 2 a 12 passos")
        lines, clean = [], []
        for i, (line, problem, step) in enumerate(self.preview_steps(steps), 1):  # every step is validated now, so nothing invalid is ever shown as part of a plan
            if problem:
                raise ComputerError(f"passo {i}: {problem}")
            lines.append(f"{i}. {line}")
            clean.append(step)
        text = f"Plano ({len(clean)} passos): {goal[:120]}\n" + "\n".join(lines) + "\nAprove o plano, ou diga o que quer mudar. Cada passo ainda pede a sua aprovação."
        return self._propose("computer.plan", text, {"goal": goal[:120], "steps": clean, "risk": "plan", "auto_ok": False})

    def find_candidates(self, word: str, limit: int = 6) -> list[Path]:
        """Files and folders of the workspace whose name is `word` (with or without the extension, ignoring case and accents): for "o rascunho"
        when the file is rascunho.txt. Hidden things and backups are left out."""
        wanted = plain(Path(word).stem if Path(word).suffix else word)
        if not wanted:
            return []
        found: list[Path] = []
        root = self.workspace
        if not root.is_dir():
            return []
        for path in sorted(root.rglob("*")):
            rel = path.relative_to(root)
            if len(rel.parts) > 4 or any(part.startswith(".") for part in rel.parts) or path.name.startswith("backup_"):
                continue
            if plain(path.stem) == wanted or plain(path.name) == plain(word):
                found.append(path)
            if len(found) >= limit:
                break
        return found

    def _plan_row(self, plan_id: str) -> tuple[list[dict], int, str] | None:
        with self._lock:
            row = self._db.execute("SELECT steps, idx, status FROM computer_plans WHERE id = ?", (plan_id,)).fetchone()
        return (json.loads(row[0]), row[1], row[2]) if row else None

    def _plan_set(self, plan_id: str, idx: int, status: str) -> None:
        with self._lock:
            self._db.execute("UPDATE computer_plans SET idx = ?, status = ? WHERE id = ?", (idx, status, plan_id))
            self._db.commit()

    def _start_plan(self, p: dict) -> str:
        plan_id = uuid.uuid4().hex
        with self._lock:
            self._db.execute("INSERT INTO computer_plans (id, steps, idx, status) VALUES (?,?,?,?)", (plan_id, json.dumps(p["steps"]), 0, "running"))
            self._db.commit()
        return "Plano aprovado.\n" + self._advance(plan_id)

    def _advance(self, plan_id: str) -> str:
        """Runs or proposes the next step. Safe steps run by themselves only when kept approved; every other step is proposed."""
        row = self._plan_row(plan_id)
        if row is None or row[2] != "running":
            return ""
        steps, idx, _ = row
        out: list[str] = []
        while idx < len(steps):
            step, link = steps[idx], {"id": plan_id, "index": idx + 1, "of": len(steps)}
            try:
                if step["type"] == "create_file":
                    action, ran = self.propose_create_file(step["path"], step["content"], plan=None if self.standing else link)
                else:
                    action, ran = self.propose_command(step["command"], plan=None if self._is_auto(step["command"]) else link)
            except ComputerError as exc:
                self._plan_set(plan_id, idx, "stopped")
                return "\n".join(out + [f"Parei no passo {idx + 1}: {exc}"])
            idx += 1
            if action is None:  # kept approved and safe: it already ran
                out.append(f"Passo {idx}: {ran}")
                continue
            self._plan_set(plan_id, idx, "running")
            out.append(f"Passo {idx} de {len(steps)} aguardando a sua aprovação.")
            return "\n".join(out)
        self._plan_set(plan_id, idx, "done")
        out.append("Plano concluído.")
        return "\n".join(out)

    def _is_auto(self, command: str) -> bool:
        try:
            return self.standing and self.validate(command).cls == SAFE
        except ComputerError:
            return False

    def reject(self, action_id: str) -> Action:
        action = super().reject(action_id)
        plan = (action.payload or {}).get("plan")
        if plan:
            self._plan_set(plan["id"], 0, "cancelled")
        return action

    # ------------------------------------------------------------------------------------------ executing (after approval)
    def _execute(self, action: Action) -> str:
        p, kind = action.payload, action.kind
        plan = p.get("plan")
        try:
            if kind == "computer.cmd":
                checked = self.validate(p["command"])  # second check, right before running
                if checked.cls != p.get("cls"):
                    raise ComputerError("a classificação do comando mudou; nada foi executado")
                result = self._run_checked(checked)
            elif kind == "computer.create_file":
                result = self._write_new(Path(p["path"]), p["content"])
            elif kind == "computer.create_document":
                result = self._write_document(p)
            elif kind == "computer.edit":
                result = self._do_edit(p)
            elif kind == "computer.revert":
                result = self._do_revert(p)
            elif kind == "computer.trash":
                result = self._do_trash(p)
            elif kind == "computer.open_app":
                if sys.platform != "darwin":
                    raise ComputerError("só no macOS")
                app, _ = find_app(p["app"], self._apps())
                if app != p["app"]:
                    raise ComputerError("o aplicativo não está mais instalado")
                self._open(["open", "-a", app])
                result = f"Abri o {app}."
            elif kind == "computer.open_path":
                target = resolve(p["path"], self.roots, must_exist=True, what="abrir")
                if target.suffix.lower() in EXECUTABLE_EXT:
                    raise ComputerError("não abro programas executáveis")
                self._open(["open", str(target)] if sys.platform == "darwin" else ["xdg-open", str(target)])
                result = f"Abri {target}."
            elif kind == "computer.plan":
                return self._start_plan(p)
            else:
                raise ComputerError("pedido inválido")
        except Exception:
            if plan:
                self._plan_set(plan["id"], 0, "stopped")
            raise
        if plan:
            more = self._advance(plan["id"])
            if more:
                result += "\n" + more
        return result
