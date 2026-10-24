"""Creating files needs the person's approval (they see the exact path and the text); opening an app, a website or an item
is done right away and reported. Nothing here runs a command line."""

import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from ..approvals import Action, ActionStore, ApprovalService
from .safety import ComputerError, check_content, check_openable_path, check_url, find_app, installed_apps, resolve_new_file


def system_open(argv: list[str]) -> None:
    """Runs one fixed opener (`open`, `xdg-open`) with arguments that were already validated. No shell."""
    subprocess.run(argv, check=True, timeout=15, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class ComputerService(ApprovalService):
    prefix = "computer."
    cancel_text = "Certo, não criei o arquivo."
    PREVIEW_LINES = 12

    def __init__(self, workspace: str, actions: ActionStore, ttl_seconds: float = 900.0, now: Callable[[], float] = time.time,
                 opener: Callable[[list[str]], None] = system_open, apps: Callable[[], dict[str, str]] = installed_apps):
        super().__init__(actions, ttl_seconds, now)
        self.workspace = Path(os.path.expanduser(workspace))
        self._open = opener
        self._apps = apps

    # ---- files: proposed, created only after approval
    def propose_create_file(self, relative: str, content: str, overwrite: bool = False) -> Action:
        target = resolve_new_file(self.workspace, relative)
        content = check_content(content)
        exists = target.exists()
        if exists and not overwrite:
            raise ComputerError(f"já existe um arquivo {target.name} em {target.parent}; escolha outro nome")
        if target.is_symlink() or (exists and not target.is_file()):
            raise ComputerError("esse destino não é um arquivo comum")
        lines = content.splitlines()
        shown = "\n".join(lines[: self.PREVIEW_LINES]) + (f"\n… (+{len(lines) - self.PREVIEW_LINES} linhas)" if len(lines) > self.PREVIEW_LINES else "")
        verb = "Substituir" if exists else "Criar"
        return self._propose("computer.create_file", f"{verb} o arquivo {target}\n{shown}",
                             {"path": str(target), "content": content, "overwrite": exists})

    def pending_confirmation(self) -> Action | None:
        waiting = self.pending()
        return waiting[-1] if waiting else None

    def _execute(self, action: Action) -> str:
        if action.kind != "computer.create_file":
            raise ComputerError("pedido inválido")
        p = action.payload
        target = resolve_new_file(self.workspace, p["path"])  # checked again at the moment of writing, not only when proposed
        check_content(p["content"])
        if target.exists() and not p.get("overwrite"):
            raise ComputerError("o arquivo passou a existir; nada foi escrito")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_symlink():
            raise ComputerError("o destino é um atalho; nada foi escrito")
        tmp = target.with_name(f".{target.name}.chakmati-tmp")
        tmp.write_text(p["content"], encoding="utf-8")
        os.replace(tmp, target)  # never leaves a half-written file
        return f"Arquivo criado: {target}"

    # ---- opening things: immediate
    def open_app(self, name: str) -> str:
        if sys.platform != "darwin":
            raise ComputerError("abrir aplicativos por aqui só funciona no macOS por enquanto")
        app, candidates = find_app(name, self._apps())
        if app is None:
            if candidates:
                raise ComputerError("qual destes? " + ", ".join(candidates))
            raise ComputerError(f"não encontrei um aplicativo chamado \"{name}\"")
        self._open(["open", "-a", app])
        return f"Abri o {app}."

    def open_url(self, url: str) -> str:
        safe = check_url(url)
        self._open(["open", safe] if sys.platform == "darwin" else ["xdg-open", safe])
        return f"Abri {safe}."

    def open_path(self, path: str) -> str:
        target = check_openable_path(path, self.workspace)
        self._open(["open", str(target)] if sys.platform == "darwin" else ["xdg-open", str(target)])
        return f"Abri {target}."
