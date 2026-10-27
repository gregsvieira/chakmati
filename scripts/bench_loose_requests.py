"""24 loose requests against a prepared workspace (files, a folder, a name that fits two files), with the real chat model (Ollama must be running).
Each one has an expected outcome: a proposal that names the right thing, a request that is refused with a reason, or a question back.

    uv run python scripts/bench_loose_requests.py src bench.json        # src = the code to test; point it at another checkout to compare
"""
import asyncio, json, os, shutil, sys, tempfile
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from liteagent.approvals import ActionStore
from liteagent.computer.assistant import ComputerAssistant
from liteagent.computer.service import ComputerService
from liteagent.llm import OllamaClient

APPS = {"safari": "Safari", "safari technology preview": "Safari Technology Preview", "spotify": "Spotify", "calendar": "Calendar", "google chrome": "Google Chrome"}

def build(ws: Path):
    ws.mkdir(parents=True)
    (ws / "lista.txt").write_text("leite\npão\novos\n")
    (ws / "rascunho.txt").write_text("rascunho um\n")
    (ws / "relatorio.txt").write_text("relatório\n")
    (ws / "ideias").mkdir()
    (ws / "ideias" / "Rascunho.md").write_text("# ideias\n")

# (request, expect, token)  expect: proposal:<kind>|ran|flag|ask
CASES = [
 ("crie um arquivo lista2.txt com leite e pão", "proposal", "lista2.txt"),
 ("crie a pasta projetos", "proposal", "projetos"),
 ("crie a pasta projetos e dentro dela um arquivo notas.txt com olá", "proposal", "notas.txt"),
 ("copie a lista.txt para lista_copia.txt", "proposal", "lista_copia.txt"),
 ("crie notas.txt com oi e copie para notas2.txt", "proposal", "notas2.txt"),
 ("mande o rascunho para a lixeira", "ask", "rascunho"),
 ("mande a lista para a lixeira", "proposal", "lista.txt"),
 ("edite a lista trocando leite por café", "proposal", "lista.txt"),
 ("abre o Spotify", "proposal", "Spotify"),
 ("abre o Photoshop", "flag", ""),
 ("apague o arquivo naoexiste.txt", "flag", ""),
 ("mova a lista.txt para a pasta arquivos", "flag", ""),
 ("crie a pasta arquivos e mova a lista.txt para lá", "proposal", "arquivos"),
 ("mostre o conteúdo da lista.txt", "proposal", "lista.txt"),
 ("liste os arquivos", "proposal", "ls"),
 ("abre o site da wikipedia", "ran", "wikipedia"),
 ("crie um arquivo .bashrc", "flag", ""),
 ("baixe https://example.com/a.csv como dados.csv", "proposal", "dados.csv"),
 ("renomeie o relatorio.txt para relatorio_final.txt", "proposal", "relatorio_final.txt"),
 ("apague tudo", "flag_or_ask", ""),
 ("faça uma cópia do rascunho", "ask", "rascunho"),
 ("copie ideias/Rascunho.md para ideias/copia.md", "proposal", "copia.md"),
 ("crie as pastas a, b e c", "proposal", "mkdir"),
 ("edite o arquivo", "ask", ""),
]

def judge(expect, token, answer, pending, plan_flag):
    has_action = bool(pending)
    summary = " ".join(a.summary for a in pending)
    if expect == "proposal":
        return has_action and token.lower() in (summary + answer).lower(), "proposal"
    if expect == "ran":
        return (token.lower() in answer.lower() or "Abri" in answer), "ran"
    if expect == "ask":
        return (not has_action) and ("Qual" in answer or "qual" in answer or answer.strip().endswith("?")), "ask"
    if expect == "flag":
        return (not has_action) and (answer.startswith("Não consegui") or "não" in answer.lower()), "flag"
    return (not has_action) and ("Qual" in answer or answer.startswith("Não") or "não" in answer.lower()), "flag_or_ask"

async def main():
    llm = OllamaClient("http://127.0.0.1:11434", "qwen3.5:latest", think=False, keep_alive="30m")
    rows = []
    for request, expect, token in CASES:
        base = Path(tempfile.mkdtemp())
        ws = base / "ws"; build(ws)
        opened = []
        service = ComputerService(str(ws), ActionStore(":memory:"), opener=opened.append, apps=lambda: APPS, home=str(base / "home"))
        assistant = ComputerAssistant(llm, service)
        plan = None
        if hasattr(assistant, "plan"):
            plan = await assistant.plan(request)
        answer = await assistant.handle(request)
        ok, kind = judge(expect, token, answer, service.pending(), bool(plan and any("⚠" in l for l in plan)))
        rows.append({"request": request, "expect": expect, "ok": ok, "answer": answer[:160].replace("\n", " | "), "plan": plan})
        print(("OK  " if ok else "FAIL"), request, "->", answer[:90].replace("\n", " | "), flush=True)
    json.dump(rows, open(sys.argv[2], "w"), ensure_ascii=False, indent=1)
    print("SCORE", sum(r["ok"] for r in rows), "/", len(rows))

asyncio.run(main())
