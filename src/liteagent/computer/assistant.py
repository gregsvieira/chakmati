"""Natural-language front end for the computer. The model only turns the PERSON's request into a small JSON (what to do, which
commands, which files); every rule (allowed commands, folders, secrets, approvals) is code in policy.py / service.py.

Only the person's own words reach the model here. A command's output is shown to the person and never sent back, and a file's
text reaches the model only for an edit the person asked for (fenced as untrusted, and refused if it holds secrets)."""

import json
import re
import subprocess
import sys
from pathlib import Path
from collections.abc import Awaitable, Callable

from ..guard import UNTRUSTED_RULE, fence, strip_markers
from ..llm import ChatClient
from . import grading
from .policy import PolicyError, resolve
from .safety import ComputerError, check_url, find_app, plain as plain_name
from .service import ComputerService

SYSTEM = """You turn a request to do something on the user's computer into JSON. Reply with ONLY one JSON object, no prose.
"action" is one of:
  "steps"      do things with commands or new files. Put them in "steps", in order (one step if the job is simple).
  "open_app"   open a program: "app" is its name (for example "Safari")
  "open_url"   open a website: "url" (add https:// if missing)
  "open_path"  open a file or folder: "path"
  "edit"       change an EXISTING text file: "path" and "instruction" (what to change)
  "revert"     undo your earlier edit of a file: "path"
  "trash"      the user wants a file or folder removed: "path" (it only goes to the Trash, never deleted)
  "other"      anything else
Each step is {"type":"command","command":"..."} or {"type":"create_file","path":"name.txt","content":"full text"}.
Commands are ONE program with plain words: no pipes, no >, no &&, no ;, no $, no wildcards, no ~. Allowed programs:
  pwd, date, ls [-la] [path], cat/head/tail/wc/stat/file <file>, grep [-nir] text file, du -sh path, mkdir [-p] folder, touch file.txt,
  cp [-r] source destination, mv source destination (new destinations only), echo text,
  python3/node/bash <script> (runs a script the user named), curl -L -o <file> https://... (download, https only).
Paths are inside the workspace folder (relative paths are fine). Use create_file to write text into a new file; never use echo for that.
For a task with several parts, give all the steps in order. Never invent files or contents the user did not ask for. Never output anything else."""

EDIT_SYSTEM = ("You edit a text file following the user's instruction. Reply with ONLY the complete new text of the file, nothing else, "
               "no explanations and no code fences." + UNTRUSTED_RULE)

HELP = ("Não entendi o que fazer no computador. Exemplos: \"crie um arquivo lista.txt com leite, pão e ovos\", \"crie a pasta projetos\", "
        "\"abre o Spotify\", \"edite a lista.txt trocando leite por café\", \"mande o rascunho.txt para a lixeira\".")


# --- Word / Excel / PowerPoint (Pages / Numbers / Keynote open them) ---------------------------------------------------------
_DOC_KIND = (
    ("pptx", re.compile(r"\b(?:slides?|apresenta[çc][ãa]o|apresenta[çc][õo]es|keynote|powerpoint|ppt)\b", re.IGNORECASE)),
    ("xlsx", re.compile(r"\b(?:planilha|numbers|excel|xlsx|tabela)\b", re.IGNORECASE)),
    ("docx", re.compile(r"\b(?:pages|word|docx|documento\s+de\s+texto|documento)\b", re.IGNORECASE)),
)
_MAKE = re.compile(r"\b(?:cri\w+|fa[çc]\w*|mont\w+|ger[ae]\w*|escrev\w+|prepar\w+)\b", re.IGNORECASE)
_WEB = re.compile(r"\b(?:internet|wikip[eé]dia|site|web|copiad\w+|pesquis\w+|pesquisad\w+|fonte)\b", re.IGNORECASE)

META_SYSTEM = """From the user's request, reply with ONLY one JSON object: {"name":"short file name without extension, no spaces","topic":"the subject to look up or write about, in a few words"}."""

SPEC_SYSTEMS = {
    "docx": """Write a text document. Reply with ONLY one JSON object: {"title":"...","paragraphs":["...","..."]}.
Use 2 to 6 paragraphs. If source text is given, copy the relevant sentences from it faithfully (do not invent facts); otherwise write it yourself. Same language as the user.""",
    "xlsx": """Make a spreadsheet. Reply with ONLY one JSON object: {"sheets":[{"name":"...","rows":[[...],[...]]}]}.
The first row is the header. A cell is a number, a text, or a formula starting with "=" over cells of the same sheet, like "=SUM(B2:B4)", "=AVERAGE(B2:B4)", "=B2*C2".
Always include the formulas the user asked for (totals, averages, products) in the right cells, and realistic sample numbers if none were given. Same language as the user.""",
    "pptx": """Make a slide deck. Reply with ONLY one JSON object: {"title":"deck title","slides":[{"title":"...","bullets":["...","..."]}]}.
Use 4 to 7 slides with 2 to 4 short bullets each (the first slide is the introduction). If source text is given, base the slides on it; do not invent facts. Same language as the user.""",
}

ACTIONS = {"steps", "open_app", "open_url", "open_path", "edit", "revert", "trash"}
STEP_TYPES = ("command", "create_file")


def _shape(data: dict) -> dict:
    """Keep only the fields we know, as the strict reading of one JSON object."""
    action = data.get("action")
    if action is None and isinstance(data.get("steps"), list):  # small models often leave "action" out when there are steps
        action = "steps"
    if action not in ACTIONS:
        return {"action": "other"}
    out: dict = {"action": action}
    for key in ("app", "url", "path", "instruction", "goal"):
        if isinstance(data.get(key), str):
            out[key] = data[key].strip()
    steps = data.get("steps")
    if isinstance(steps, list):
        out["steps"] = [s for s in steps if isinstance(s, dict) and s.get("type") in STEP_TYPES][:12]
    return out


def _usable(intent: dict) -> bool:
    return intent["action"] != "other" and (intent["action"] != "steps" or bool(intent.get("steps")))


def _fix_step(step: object) -> object:
    """A step missing its "type" (or with an invented one) gets it from the fields it carries."""
    if not isinstance(step, dict) or step.get("type") in STEP_TYPES:
        return step
    if isinstance(step.get("command"), str):
        return {**step, "type": "command"}
    if isinstance(step.get("path"), str) and isinstance(step.get("content"), str):
        return {**step, "type": "create_file"}
    return step


def _repair(data: dict) -> dict | None:
    """Fix the shape slips small models make; the content is never invented, and policy.py still judges every command.

    Only used when the strict reading found nothing to do, and never on a reply that says "other" itself."""
    kind = data.get("type")
    if data.get("action") not in ACTIONS:
        if kind in ACTIONS:  # {"type":"open_url","url":...}: "type" where "action" belongs
            return {**data, "action": kind}
        bare = _fix_step(data)
        if isinstance(bare, dict) and bare.get("type") in STEP_TYPES:  # one step with no "steps" around it
            return {"action": "steps", "steps": [bare]}
    steps = data.get("steps")
    if isinstance(steps, list):
        fixed = [_fix_step(s) for s in steps]
        if not any(isinstance(s, dict) and s.get("type") in STEP_TYPES for s in fixed):
            only = fixed[0] if len(fixed) == 1 else None  # one action dressed as a step; with several we do not guess
            if isinstance(only, dict) and only.get("type") in ACTIONS:
                return {**only, "action": only["type"]}
            return None
        return {**data, "action": "steps", "steps": fixed}
    return None


def parse_intent(reply: str) -> dict:
    first, last = reply.find("{"), reply.rfind("}")
    if first == -1 or last <= first:
        return {"action": "other"}
    try:
        data = json.loads(reply[first : last + 1])
    except json.JSONDecodeError:
        return {"action": "other"}
    if not isinstance(data, dict):
        return {"action": "other"}
    intent = _shape(data)
    if _usable(intent) or "other" in (data.get("action"), data.get("type")):
        return intent if _usable(intent) else {"action": "other"}
    fixed = _repair(data)
    if fixed is not None:
        repaired = _shape(fixed)
        if _usable(repaired):
            return repaired
    return intent


Gather = Callable[[str], Awaitable[tuple[str, list[str]]]]


_GRADE = re.compile(r"\b(?:corrij\w+|corrig\w+|corre[çc][ãa]o)\b.{0,60}\bprovas?\b|\bprovas?\b.{0,60}\b(?:corrij\w+|corrig\w+)", re.IGNORECASE)
_FOLDER = re.compile(r"\bpasta\s+[\"“']?([\w\-./ ]+?)[\"”']?(?=\s*(?:[,.;:(]|\bque\b|\bcom\b|\bem\b|\bonde\b|$))", re.IGNORECASE)
_GABARITO = re.compile(r"gabarito\s*(?:[ée]|:)?\s*:?\s*((?:\d{1,3}\s*[-:.)]?\s*[A-Ea-e]\b(?:\s*[,;-]\s*|\s+e\s+|\s+)?)+)", re.IGNORECASE)
_POINTS = re.compile(r"(?:vale|valendo|vale\s+cada)\s+(\d+(?:[.,]\d+)?)\s*pontos?|(\d+(?:[.,]\d+)?)\s*pontos?\s+(?:por|cada)", re.IGNORECASE)


_TRASH = re.compile(r"\b(?:mand\w+|mov\w+|jog\w+|colo\w+|envi\w+|leve\w*)\s+(?:o\s+|a\s+|os\s+|as\s+)?(?:arquivo\s+|pasta\s+)?(.+?)\s+(?:para|pra|na|à|a)\s+(?:a\s+)?lixeira\b", re.IGNORECASE)
_FILE_VERB = re.compile(r"\b(?:edit\w+|apag\w+|exclu\w+|delet\w+|remov\w+|renome\w+|mov\w+|copi\w+|cop[ií]a|duplic\w+|abr\w+)\b", re.IGNORECASE)
_MASS = re.compile(r"\b(?:apag\w+|delet\w+|exclu\w+|remov\w+|limp\w+|esvazi\w+)\b.{0,25}\b(?:tudo|todos|todas|inteir\w+)\b", re.IGNORECASE)
_COPY_OF = re.compile(r"\b(?:fa[çc]a|crie|fazer|criar|tire)\s+(?:uma\s+)?c[óo]pia\s+(?:de\s+|do\s+|da\s+|dos\s+|das\s+)(?:o\s+|a\s+)?(?:arquivo\s+|pasta\s+)?(.+)$", re.IGNORECASE)
_DELETE_VERB = re.compile(r"\b(?:apag\w+|exclu\w+|delet\w+|remov\w+)\b", re.IGNORECASE)
_EXPLAIN = re.compile(r"\b(?:expli[cq]\w*|justific\w+|coment\w+|por\s*qu[êe]\b.{0,30}\berr\w+)", re.IGNORECASE)
MAX_EXPLAIN_CALLS = 40
SOLVE_SYSTEM = ("You are a maths teacher. Solve the multiple-choice question step by step, in Brazilian Portuguese, in at most 6 short lines, showing the calculations. "
                "Your solution MUST end at the correct option given by the teacher. Reply with the solution only.")
EXPLAIN_SYSTEM = ("You are a maths teacher writing feedback for a student. In Brazilian Portuguese and in at most 3 short sentences, say why the option the student "
                  "chose is wrong (what mistake leads to it, with the calculation that gives that number if you can) and what the right reasoning is. "
                  "Use the worked solution. Be kind and concrete. Reply with the feedback only.")


_LATEX = [
    (re.compile(r"\\\(|\\\)|\\\[|\\\]|(?<!R)\$"), ""),
    (re.compile(r"\\text\{([^}]*)\}"), r"\1"), (re.compile(r"\\(?:d?frac)\{([^}]*)\}\{([^}]*)\}"), r"(\1)/(\2)"),
    (re.compile(r"\\sqrt\{([^}]*)\}"), r"raiz(\1)"), (re.compile(r"\\times|\\cdot"), "×"), (re.compile(r"\\implies|\\Rightarrow"), "=>"),
    (re.compile(r"\\approx"), "≈"), (re.compile(r"\\(?:left|right|,|;|!)"), ""), (re.compile(r"\^\{?2\}?"), "²"),
    (re.compile(r"\*\*"), ""), (re.compile(r"\\"), ""),
]


def plain_math(text: str) -> str:
    """The model writes LaTeX and Markdown; a spreadsheet cell should read as plain text."""
    text = text.replace("\\$", "§")  # a real "R\$" is a dollar sign, not LaTeX
    for pattern, repl in _LATEX:
        text = pattern.sub(repl, text)
    return " ".join(text.replace("§", "$").split())


_OPT = r"(?:alternativa|op[çc][ãa]o|letra)\s*\(?([A-E])\b"
_SAYS_CORRECT = [
    re.compile(r"(?:correta|certa|correto|certo|gabarito)\W[^.]{0,50}?" + _OPT, re.IGNORECASE),            # "a resposta correta é a alternativa B"
    re.compile(_OPT + r"\)?\s*(?:\([^)]*\)\s*)?(?:[^.]{0,25}?\bcorrespond\w*|[eé] a (?:correta|certa)|[eé] o (?:correto|certo))", re.IGNORECASE),  # "a alternativa B é a correta"
    re.compile(r"correspond\w*\s+(?:à|a|ao)\s+" + _OPT, re.IGNORECASE),                                    # "correspondendo à alternativa B"
]


_RAMBLING = re.compile(r"\b(?:vamos refazer|n[ãa]o,\s|na verdade|espere|hmm|let me|wait)\b|\?.*\?", re.IGNORECASE)


def rambling(text: str) -> bool:
    """The model thinking out loud and correcting itself in the answer: not something to hand to a student."""
    return bool(_RAMBLING.search(text))


def contradicts_key(text: str, right: str, chosen: str = "") -> bool:
    """True when the explanation says some OTHER option is the correct one (a small model sometimes argues against the teacher's own key).
    The option the student chose may be named as what their wrong number corresponds to: that is not a contradiction."""
    named = {m.group(1).upper() for pattern in _SAYS_CORRECT for m in pattern.finditer(text)}
    return bool(named - {right.upper(), chosen.upper()})


def document_kind(text: str) -> str | None:
    """"pptx" | "xlsx" | "docx" when the request is to make such a file, decided by code and not by the model."""
    if not _MAKE.search(text):
        return None
    return next((kind for kind, pattern in _DOC_KIND if pattern.search(text)), None)


def _json_object(reply: str) -> dict | None:
    first, last = reply.find("{"), reply.rfind("}")
    try:
        data = json.loads(reply[first : last + 1]) if 0 <= first < last else None
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


class ComputerAssistant:
    def __init__(self, llm: ChatClient, service: ComputerService, gather: Gather | None = None, solver: ChatClient | None = None, models=None, reasoning_for=None):
        self._llm = llm
        self._solver = solver  # works out the questions of an exam: a stronger model when one is given...
        self._models = models  # ...or the one the catalog finds installed (liteagent.models.ModelCatalog)
        self._reasoning_for = reasoning_for  # (model name) -> a chat client for it
        self._intents: dict[str, dict] = {}  # what the model made of a request, kept from the plan to the answer so the model is asked once
        self._service = service
        self._gather = gather  # (topic) -> (text found on the internet, source urls); None = no web access

    async def _document(self, kind: str, request: str) -> str:
        meta = _json_object(await self._llm.chat([{"role": "system", "content": META_SYSTEM}, {"role": "user", "content": request}])) or {}
        topic = str(meta.get("topic") or request)[:120]
        name = re.sub(r"[^a-z0-9_-]+", "-", plain_name(str(meta.get("name") or topic))).strip("-")[:40] or "documento"
        source, urls = "", []
        acronyms = sorted(set(re.findall(r"\b[A-Z]{2,6}\b", request)))
        topic = " ".join([topic, *(a for a in acronyms if a not in topic)])[:140]  # the model may drop (or invent a meaning for) "MCP": it stays in the query
        if self._gather is not None and (_WEB.search(request) or kind == "pptx"):
            try:
                source, urls = await self._gather(topic)
            except Exception:
                source, urls = "", []
            if not source or not all(a in source for a in acronyms):  # pages about something else that shares the letters: never build on them
                return (f"Não encontrei fontes que falem de {', '.join(acronyms) or topic}. Pode dizer o nome completo "
                        "(por exemplo, “Model Context Protocol da Anthropic”)?")
        user = request
        if source:
            user += f"\n\nSource text (from {', '.join(urls[:3])}):\n{fence(source, 'web')}"
        system = SPEC_SYSTEMS[kind] + " Write in the language of the user's request, even if the source text is in another language (translate it)." + (UNTRUSTED_RULE if source else "")
        spec = None
        for _ in range(2):  # a small model sometimes slips on the JSON: ask once more
            spec = _json_object(await self._llm.chat([{"role": "system", "content": system}, {"role": "user", "content": user}]))
            if spec:
                break
        if not spec:
            return "Não consegui montar o conteúdo do documento. Pode pedir de novo com mais detalhes?"
        if kind == "docx" and urls:
            spec["sources"] = urls[:3]
        action = self._service.propose_create_document(f"{name}.{kind}", kind, spec)
        first, *rest = action.summary.splitlines()
        return f"{first}\nConfirma? Diga sim ou não, ou aprove no painel.\n[[action:{action.id}]]"

    async def _grade(self, text: str) -> str:
        """"Corrija as provas da pasta X... gabarito 1E - 2B": reading and grading are done by code from the person's own words. The model only
        writes the explanations of the mistakes, when they are asked for, and those go in the spreadsheet as text for the teacher to check."""
        folder, gabarito = _FOLDER.search(text), _GABARITO.search(text)
        if not folder:
            return "Em que pasta (dentro de ~/Documents/Chakmati) estão as provas? Diga “as provas da pasta provas”."
        if not gabarito:
            return "Qual é o gabarito? Escreva assim: “gabarito: 1E - 2B - 3B”."
        pts = _POINTS.search(text)
        points = float((pts.group(1) or pts.group(2)).replace(",", ".")) if pts else 1.0
        shown_key = gabarito.group(1).strip(" ,;-")
        key = grading.parse_key(shown_key)
        target, exams, unreadable = self._service.read_exam_folder(folder.group(1).strip())
        spec, summary = grading.grade(exams, key, points)
        lines = [f"Li {summary['alunos']} provas e corrigi com o gabarito {shown_key} (cada acerto vale {points:g})."]
        lines.append("Acertaram tudo: " + (", ".join(summary["acertaram_tudo"]) or "ninguém") + ".")
        if _EXPLAIN.search(text):
            rows, made = await self._explanations(exams, key)
            if rows:
                spec["sheets"].append({"name": "Explicações", "rows": rows})
                lines.append(f"Na aba Explicações, {len(rows) - 1} erros explicados (escritos pelo modelo local: confira antes de passar para os alunos).")
            elif made is not None:
                lines.append(made)
        if summary["com_observacao"]:
            lines.append(f"{summary['com_observacao']} provas têm questão em branco, com mais de uma marca ou com algo para conferir: está na coluna Observações.")
        if unreadable:
            lines.append("Não consegui ler: " + ", ".join(unreadable) + ". Corrija esses à mão.")
        action = self._service.propose_create_document(f"correcao-{target.name}.xlsx", "xlsx", spec)
        return "\n".join([*lines, f"{action.summary.splitlines()[0]}", "Confirma? Diga sim ou não, ou aprove no painel.", f"[[action:{action.id}]]"])

    async def _explanations(self, exams: list, key: dict[int, str]) -> tuple[list, str | None]:
        """(rows for the sheet, a message if it could not be done). One worked solution per question and one explanation per wrong option
        chosen by someone: written once and reused for every student who made that mistake."""
        texts = grading.question_texts(exams)
        wrong = grading.mistakes(exams, key)
        solver = await self._solver_client()
        if not wrong:
            return [], "Ninguém errou nada, então não há o que explicar."
        solutions: dict[int, str] = {}
        cache: dict[tuple[int, str], str] = {}
        rows = [["Aluno", "Questão", "Marcou", "Correta", "Por que a escolha está errada"]]
        calls = 0
        for student, q, marked, right in wrong:
            question = texts.get(q)
            if not marked:
                rows.append([student, f"Q{q}", "em branco", right, f"Não respondeu. A alternativa correta é {right}" + (f") {question.options[right]}" if question and right in question.options else ".")])
                continue
            for letter in marked:
                if letter == right:
                    continue  # (two boxes marked, one of them the right one: the mistake is the other)
                if question is None or letter not in question.options or right not in question.options:
                    cache[(q, letter)] = f"Marcou {letter}, mas a correta é {right}. Não consegui ler o enunciado desta questão para explicar."
                if (q, letter) not in cache:
                    if calls >= MAX_EXPLAIN_CALLS:
                        cache[(q, letter)] = f"Marcou {letter}, mas a correta é {right}."
                    else:
                        if q not in solutions:
                            solutions[q] = await self._solve(question, right, solver)
                            calls += 1
                        cache[(q, letter)] = await self._explain(question, solutions[q], letter, right)
                        calls += 1
                rows.append([student, f"Q{q}", letter if len(marked) == 1 else f"{marked} (várias)", right, cache[(q, letter)]])
        return rows, None

    def _question_block(self, question) -> str:
        options = "\n".join(f"{letter}) {text}" for letter, text in sorted(question.options.items()))
        return fence(f"{question.stem}\n{options}", "exam")

    # ------------------------------------------------------------------------------------------------ the plan, shown before anything is done
    async def plan(self, text: str) -> list[str] | None:
        """The steps this request will take, as the person will see them first (None for a simple one: "abre o Spotify"). Built from the
        request and from a look at what is there (is the folder there? are the exams text or scans? is the stronger model installed?),
        so it also says which tool or model each step needs."""
        if _GRADE.search(text):
            return await self._plan_grade(text)
        kind = document_kind(text)
        if kind:
            return self._plan_document(kind, text)
        return await self._plan_loose(text)

    async def _plan_loose(self, text: str) -> list[str] | None:
        """A request to do something on the computer, outside the big flows: the steps the model understood, each one already checked
        against the disk and the policy, so a problem shows up in the plan (and not only after the person approved). The model is asked
        once: what it made of the request is kept for the answer."""
        intent = await self._parse(text)
        if len(self._intents) >= 8:
            self._intents.pop(next(iter(self._intents)))
        self._intents[text] = intent
        if intent["action"] == "other":
            return None
        lines = self._prepare(intent)[1]
        shown = len(lines) >= 2 or any("⚠" in line for line in lines) or intent["action"] in {"edit", "trash", "revert"}
        return lines if shown else None

    async def _plan_grade(self, text: str) -> list[str] | None:
        folder, gabarito = _FOLDER.search(text), _GABARITO.search(text)
        if not folder or not gabarito:
            return None  # the answer will ask for what is missing
        name = folder.group(1).strip()
        pts = _POINTS.search(text)
        points = (pts.group(1) or pts.group(2)).replace(".", ",") if pts else "1"
        steps = []
        try:
            target = self._service.workspace / name
            found = grading.inspect_folder(target) if target.is_dir() else None
        except Exception:
            found = None
        steps.append(f"Procurar a pasta «{name}» em {self._service.workspace}: " + (("a pasta não tem provas (PDF, JPG ou PNG), vou avisar." if not found["files"] else f"achei {found['files']} arquivos.") if found else "não achei, vou avisar."))
        if found and found["files"]:
            direct, ocr_n = found["text_pdf"], found["scanned_pdf"] + found["images"]
            how = []
            if direct:
                how.append(f"{direct} PDF com texto: leitura direta pelos caracteres")
            if ocr_n:
                from .. import extras
                how.append(f"{ocr_n} escaneados ou fotos: leitura por OCR" + ("" if extras.available("ocr") else " (⚠ o OCR não está instalado: `uv sync --extra ocr`)"))
            steps.append("Verificar como ler cada prova: " + "; ".join(how) + ".")
        else:
            steps.append("Verificar como ler cada prova (texto direto ou OCR, se for imagem).")
        steps.append("Ler o nome e a marcação de cada aluno (nas imagens, medindo o quadradinho de cada alternativa).")
        steps.append(f"Comparar com o gabarito {gabarito.group(1).strip(' ,;-')} e calcular acertos e nota ({points} por acerto), sinalizando questão em branco ou com duas marcas.")
        if _EXPLAIN.search(text):
            if self._solver is not None:
                why = "o modelo de raciocínio configurado"
            elif self._models is not None:
                why = (await self._models.reasoning()).why
            else:
                why = "o modelo padrão"
            steps.append(f"Resolver cada questão com {why} e explicar o erro de cada aluno, descartando explicação que contrarie o gabarito.")
        steps.append("Montar a planilha com fórmulas (abre no Numbers) e esperar a sua aprovação antes de salvar.")
        return steps

    def _plan_document(self, kind: str, text: str) -> list[str]:
        label = {"docx": "o documento (Pages)", "xlsx": "a planilha (Numbers)", "pptx": "os slides (Keynote)"}[kind]
        steps = [f"Entender o pedido: criar {label}."]
        if self._gather is not None and (_WEB.search(text) or kind == "pptx"):
            steps.append("Buscar textos na internet sobre o tema (pelo mecanismo de pesquisa, sem abrir o navegador) e conferir se falam mesmo do assunto.")
        steps.append("Escrever o conteúdo com o modelo padrão" + (", usando o que foi encontrado e citando a fonte." if self._gather is not None and (_WEB.search(text) or kind == "pptx") else "."))
        steps.append(f"Gerar o arquivo .{kind} na pasta de trabalho, conferindo o formato" + (" e as fórmulas permitidas." if kind == "xlsx" else "."))
        steps.append(f"Mostrar o que vai ser criado e esperar a sua aprovação antes de salvar e abrir.")
        return steps

    async def _solver_client(self):
        if self._solver is not None:
            return self._solver
        if self._models is not None and self._reasoning_for is not None:
            choice = await self._models.reasoning()
            if choice.model:
                return self._reasoning_for(choice.model)
        return self._llm

    async def _solve(self, question, right: str, solver) -> str:
        reply = await solver.chat([
            {"role": "system", "content": SOLVE_SYSTEM + UNTRUSTED_RULE},
            {"role": "user", "content": f"{self._question_block(question)}\nCorrect option (from the teacher's key): {right}) {question.options[right]}"},
        ])
        return plain_math(strip_markers(reply))[:900]

    async def _explain(self, question, solution: str, letter: str, right: str) -> str:
        reply = await self._llm.chat([
            {"role": "system", "content": EXPLAIN_SYSTEM + UNTRUSTED_RULE},
            {"role": "user", "content": f"{self._question_block(question)}\nWorked solution: {solution}\nCorrect option: {right}) {question.options[right]}\n"
                                        f"Option the student chose: {letter}) {question.options[letter]}"},
        ])
        text = plain_math(strip_markers(reply))
        if contradicts_key(text, right, letter) or rambling(text):  # never hand the teacher an explanation that argues against her key, or that is the model arguing with itself
            return f"Marcou {letter}, mas a correta é {right}. O modelo local não conseguiu justificar com segurança: confira esta questão à mão."
        return text[:650] + ("…" if len(text) > 650 else "")

    async def handle(self, text: str) -> str:
        if _GRADE.search(text):
            try:
                return await self._grade(text)
            except ComputerError as exc:
                return f"Não consegui: {exc}."
        kind = document_kind(text)
        if kind is not None:
            try:
                return await self._document(kind, text)
            except ComputerError as exc:
                return f"Não consegui: {exc}."
        intent = await self._intent(text)
        if intent.get("ask"):  # something the request does not say (which file? which app? which of these?): ask, do not guess
            return intent["ask"]
        try:
            return await self._act(intent, text)
        except ComputerError as exc:
            return f"Não consegui: {exc}."
        except (OSError, subprocess.SubprocessError, UnicodeDecodeError) as exc:
            return f"Não consegui: {exc}."

    def _by_rule(self, text: str) -> dict | None:
        """Requests whose words settle what is meant: decided here, before (and without) the model, which gets these wrong now and then.
        "...para a lixeira" is the trash, "uma cópia do X" is a copy, and "apague tudo" is never done in one go."""
        if _MASS.search(text):
            return {"action": "other", "ask": "Não apago nem mando tudo para a lixeira de uma vez. Diga qual arquivo ou pasta (um de cada vez)."}
        if m := _TRASH.search(text):
            return {"action": "trash", "path": m.group(1).strip(" \"'“”")}
        if m := _COPY_OF.search(text):
            word = m.group(1).strip(" \"'“”.")
            found = self._service.find_candidates(word)
            if len(found) == 1:
                src = found[0]
                return {"action": "steps", "steps": [{"type": "command", "command": f"cp {src.relative_to(self._service.workspace).as_posix()} {src.with_name(src.stem + '_copia' + src.suffix).relative_to(self._service.workspace).as_posix()}"}]}
            if len(found) > 1:
                return {"action": "other", "ask": "Qual destes? " + ", ".join(p.relative_to(self._service.workspace).as_posix() for p in found)}
        return None

    async def _parse(self, text: str) -> dict:
        ruled = self._by_rule(text)
        if ruled is not None:
            return self._prepare(ruled)[0]
        reply = await self._llm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": text}])
        intent = parse_intent(reply)
        if intent["action"] == "other" or (intent["action"] == "steps" and not intent.get("steps")):  # a small model sometimes slips: ask once more
            reply = await self._llm.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": text + "\n\nReply with the JSON object only."}])
            intent = parse_intent(reply)
        if intent["action"] == "other":
            intent = self._fallback(text)
        return self._prepare(intent)[0]

    @staticmethod
    def _fallback(text: str) -> dict:
        """The model could not read the request. Two things are still certain from the words alone: "... para a lixeira" names what goes to the
        trash, and a request with a file verb and no file name needs a question, not the general help."""
        named = re.search(r"\b[\w-]+\.[A-Za-z0-9]{1,5}\b|/", text)
        if _DELETE_VERB.search(text) and named:  # "apague o x.txt": it goes to the trash (nothing is deleted); the plan says if it is not there
            return {"action": "trash", "path": named.group(0)}
        if _FILE_VERB.search(text) and not named:
            return {"action": "other", "ask": "Qual arquivo ou pasta, e o que você quer fazer com ele? Diga o nome (dentro da pasta de trabalho)."}
        return {"action": "other"}

    async def _intent(self, text: str) -> dict:
        cached = self._intents.pop(text, None)
        return cached if cached is not None else await self._parse(text)

    # ------------------------------------------------------------------------------------------------ checking a request before it is shown
    def _prepare(self, intent: dict) -> tuple[dict, list[str]]:
        """(the intent with names made exact or a question to ask, the lines of the plan). Pure checks against the disk and the policy:
        nothing is proposed, nothing is run. A file named without its extension is found; a name that fits several asks which one."""
        s = self._service
        kind = intent["action"]
        lines: list[str] = []
        ask = None
        if kind == "steps":
            for i, (line, problem, _) in enumerate(s.preview_steps(intent.get("steps") or []), 1):
                lines.append(f"{i}. {line}" + (f"  ⚠ {problem}" if problem else ""))
        elif kind == "open_app":
            if not intent.get("app"):
                ask = "Qual aplicativo você quer abrir?"
            elif sys.platform != "darwin":
                lines.append("Abrir o aplicativo  ⚠ só funciona no macOS por enquanto")
            else:
                app, candidates = find_app(intent["app"], s._apps())
                if app:
                    lines.append(f"Abrir o aplicativo {app}")
                elif candidates:
                    ask = "Qual destes aplicativos? " + ", ".join(candidates)
                else:
                    lines.append(f"Abrir o aplicativo {intent['app']}  ⚠ não encontrei esse aplicativo instalado")
        elif kind == "open_url":
            if not intent.get("url"):
                ask = "Qual site você quer abrir?"
            else:
                try:
                    lines.append(f"Abrir o site {check_url(intent['url'])}")
                except ComputerError as exc:
                    lines.append(f"Abrir o site {intent['url'][:60]}  ⚠ {exc}")
        elif kind in {"open_path", "edit", "revert", "trash"}:
            word = intent.get("path", "")
            if not word:
                ask = "Qual arquivo ou pasta? Diga o nome (dentro de " + str(s.workspace) + ")."
            else:
                exact = None
                try:
                    exact = resolve(word, s.roots, must_exist=True, what="caminho", editable=True)
                except PolicyError:
                    pass
                if exact is None:
                    found = s.find_candidates(word)
                    if len(found) == 1:
                        intent = {**intent, "path": str(found[0])}
                        word = found[0].name
                    elif len(found) > 1:
                        ask = "Qual destes? " + ", ".join(p.relative_to(s.workspace).as_posix() for p in found)
                if ask is None:
                    name = Path(intent["path"]).name if exact is None else exact.name
                    problem = None
                    try:
                        if kind == "edit":
                            s._editable(intent["path"])
                        elif kind in {"open_path", "trash"}:
                            resolve(intent["path"], s.roots, write=(kind == "trash"), editable=(kind == "trash"), must_exist=True, what="caminho")
                    except (PolicyError, ComputerError) as exc:
                        problem = str(exc)
                    text = {"open_path": f"Abrir {name} com o programa padrão", "edit": f"Editar {name}: o original fica como backup_{name} e dá para reverter",
                            "trash": f"Mover {name} para a lixeira (dá para recuperar)", "revert": f"Reverter a última edição de {name}"}[kind]
                    lines.append(text + (f"  ⚠ {problem}" if problem else ""))
        if ask:
            intent = {"action": "other", "ask": ask}
        return intent, lines

    async def _act(self, intent: dict, request: str) -> str:
        s = self._service
        match intent["action"]:
            case "steps":
                steps = intent.get("steps") or []
                if not steps:
                    return HELP
                if len(steps) >= 2:
                    action = s.propose_plan(intent.get("goal") or request, steps)
                    return f"{action.summary}\n[[action:{action.id}]]"
                step = steps[0]
                if step["type"] == "create_file":
                    action, ran = s.propose_create_file(step.get("path", ""), step.get("content", ""))
                else:
                    action, ran = s.propose_command(step.get("command", ""))
                if action is None:
                    return ran or "Feito."
                first = action.summary.splitlines()[0]
                return f"{first}\nConfirma? Diga sim ou não, ou aprove no painel.\n[[action:{action.id}]]"
            case "open_app":
                action = s.propose_open_app(intent.get("app", ""))
                return f"{action.summary}. Confirma? Diga sim ou não.\n[[action:{action.id}]]"
            case "open_path":
                action = s.propose_open_path(intent.get("path", ""))
                return f"{action.summary}. Confirma? Diga sim ou não.\n[[action:{action.id}]]"
            case "open_url":
                return s.open_url(intent.get("url", ""))
            case "trash":
                action = s.propose_trash(intent.get("path", ""))
                return f"{action.summary.splitlines()[0]}. Confirma? Diga sim ou não.\n[[action:{action.id}]]"
            case "revert":
                action = s.propose_revert(intent.get("path", ""))
                return f"{action.summary.splitlines()[0]}. Confirma? Diga sim ou não.\n[[action:{action.id}]]"
            case "edit":
                path, old = s.read_for_edit(intent.get("path", ""))
                instruction = intent.get("instruction") or request
                new = await self._llm.chat([
                    {"role": "system", "content": EDIT_SYSTEM},
                    {"role": "user", "content": f"Instruction: {instruction}\n\nCurrent file {path.name}:\n{fence(old, 'file')}"},
                ])
                action = s.propose_edit(str(path), strip_markers(_unfence(new)))
                return f"{action.summary.splitlines()[0]}. Confirma? Diga sim ou não.\n[[action:{action.id}]]"
            case _:
                return HELP


def _unfence(text: str) -> str:
    t = text.strip("\n")
    if t.startswith("```") and t.rstrip().endswith("```"):
        lines = t.splitlines()
        return "\n".join(lines[1:-1]) + "\n"
    return t if t.endswith("\n") else t + "\n"
