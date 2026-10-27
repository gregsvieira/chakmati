# Chakmati

Local assistant engine: simple messages answer inline in seconds; slow work
(research, multi-step tasks) runs as background jobs.

## Run

    uv sync
    ollama pull qwen3.5:latest        # or set LITEAGENT_CHAT_MODEL
    uv run python -m liteagent.main   # http://127.0.0.1:8765

    curl -s localhost:8765/message -H 'content-type: application/json' \
         -d '{"text":"olá"}'
    curl -s localhost:8765/message -H 'content-type: application/json' \
         -d '{"text":"pesquise a versão atual do Python"}'   # returns a job_id
    curl -s localhost:8765/jobs/<job_id>

## Optional pieces (extras)

The base install is small (about 125 MB). Voice and microphone are opt-in:

    uv sync --extra voice     # enhanced voice (Piper) and WhatsApp voice notes
    uv sync --extra listen    # speech recognition (faster-whisper) for "talk to Chakmati"
    uv sync --extra voice --extra listen    # both (about 250 MB more)

Without them the engine starts normally; each feature answers with what to install (`/voice/status` has `engine_ready`,
`/transcribe` returns 503 naming the extra). If you used voice or the microphone before, run the command above once.
Development (`uv sync`) installs both so the whole test suite runs.

## Streaming (Server-Sent Events)

    curl -N localhost:8765/message/stream -H 'content-type: application/json' -d '{"text":"pesquise a capital da Austrália"}'
    curl -N localhost:8765/jobs/<job_id>/stream      # follow an existing job; late/reconnecting clients get the text from the start

Each line is `data: {json}`. Event types: `route` (`chat|research|task`), `job` (slow work was queued),
`status` (`queued|running|done|failed`), `delta` (a piece of text), `done` (full `result`), `error`.
Chat replies stream directly; research/task replies stream as the worker produces them.
`GET /jobs/<id>` also returns `partial`, the text so far.

## Calendar (agenda)

Off by default. Turn it on with `LITEAGENT_CALENDAR_BACKEND=auto` (macOS Calendar.app on a Mac, an `.ics` file elsewhere),
`macos`, or `ics` (file at `LITEAGENT_CALENDAR_ICS_PATH`, default `agenda.ics`). On the first use macOS asks you to allow access.

Ask in natural language ("o que tenho amanhã?", "marque dentista dia 30 às 9h", "cancele a reunião de sexta").
Reading is immediate. **Writing is always a proposal that you approve**: nothing is created or deleted until the UI calls

    curl localhost:8765/actions                                   # pending proposals
    curl -X POST -H 'X-LiteAgent-UI: 1' localhost:8765/actions/<id>/approve    # or /reject
    curl 'localhost:8765/agenda/events?start=2026-10-24T00:00:00-03:00&end=2026-10-25T00:00:00-03:00'

The model only turns your request into a small JSON; event titles and notes are never sent back to it, so text inside an
event cannot instruct the agent. Proposals expire after 1 hour. To cancel, mention the calendar or a time
("cancele o dentista **de sexta**", "... **da agenda**"). Not implemented yet: Windows (Outlook) and Linux (Evolution/CalDAV) native backends.

## WhatsApp (via OpenWA)

Off by default. **Read this first:** OpenWA drives WhatsApp Web, which WhatsApp's terms do not allow; the linked number can be
banned. Use a secondary number, keep volumes low, never expose OpenWA beyond 127.0.0.1.

    scripts/openwa.sh setup      # once: installs OpenWA and its own Node.js under ~/.lite-agent/openwa (system Node untouched)
    scripts/openwa.sh start      # opens a window with a QR code: WhatsApp > Linked devices > Link a device
    LITEAGENT_WHATSAPP_BACKEND=openwa uv run python -m liteagent.main

Then, in natural language: "tenho mensagens novas?", "o que o João disse?", "resuma a conversa com a Maria",
"manda pro João: chego em 10 min". After the first login the session is kept; later use `scripts/openwa.sh start-bg`.

Safety model (same as the calendar): reading is free, **sending is always a proposal you approve** in the same inbox
(`GET /actions`, `POST /actions/<id>/approve` with `X-LiteAgent-UI: 1`). The recipient is matched by code against your chat
list (ambiguous names ask which one), the text sent is exactly what you wrote and is shown before approval, approved sends are
limited to 20/hour with a 3 s gap, and message contents are treated as untrusted data: they never trigger a send. Summaries
are the only place where other people's text reaches the local model; it is quoted, cleaned, size-capped, and its output is text only.

    curl localhost:8765/whatsapp/status
    curl 'localhost:8765/whatsapp/chats?unread=true'

## Browser agent (live screenshots)

Off by default. Needs Chrome installed and `uv sync --extra browser`; turn it on with `LITEAGENT_BROWSER_BACKEND=chrome`.

    uv run python -m liteagent.main
    curl -N localhost:8765/message/stream -H 'content-type: application/json' \
         -d '{"text":"use o navegador para pesquisar a capital da Austrália"}'

Ask for it by name ("use o navegador...", "pelo Chrome...", "navegue até..."). A headless Chrome (no window opens; `LITEAGENT_BROWSER_HEADLESS=0` shows it; its own profile in
`~/.lite-agent/browser`, never yours) opens and works one step at a time; each step emits a `screenshot` event
(`job_id`, `step`, `url`, `title`, `note`) and the picture is at `GET /jobs/<id>/frames/<step>` (JPEG; the last 20 jobs are kept in
`~/.lite-agent/frames`). The desktop panel shows the latest screenshot with what it was doing, replaced at each step.
It drives Chrome with Playwright (`channel="chrome"`): no driver to match to the browser's version, nothing extra to download.
Safety: only public http(s) addresses open (never localhost, the home network or `file:`), passwords are never typed, page text is
quoted as data and never obeyed, and the model can only pick from a fixed set of actions (goto, click, type, scroll, back, done).

## Documents (Pages, Numbers, Keynote)

Needs `uv sync --extra documents`. "crie um documento no Pages com título e texto da Wikipedia sobre X", "monte uma planilha no
Numbers com soma e média", "crie slides sobre X" make a `.docx` / `.xlsx` / `.pptx` in the workspace (`~/Documents/Chakmati`) and
open it in Pages / Numbers / Keynote, where you save it in their own format. It is always a proposal you approve (even with "manter aprovado").
Spreadsheet formulas are limited to an allow-list (SUM, AVERAGE, MIN, MAX, COUNT, ROUND, IF, ABS, PRODUCT, MEDIAN over cells of the same
sheet); text found on the internet is fenced as untrusted and the sources are listed in the document.

### Grading exams (PDF with an "X" in the chosen box)

"Corrija as provas da pasta provas, gabarito: 1E - 2B - 3B, cada acerto vale 1 ponto, monte uma planilha no Numbers": reads every PDF
in that folder of the workspace, finds the student's name (`Aluno: ...`) and the `[X]` marks, compares them with the key you wrote and proposes
a spreadsheet (answers, `Acertos` and `Nota` as formulas, class average, and a column flagging blank or double-marked questions, which count as wrong).
The reading is done by code, not by the model. Limits: up to 100 files, and the layout `[ ] A) ...` (a box before each option, an X written in it).

**Scans and phone photos** (PDF with no text, JPG, PNG): `uv sync --extra ocr`. An OCR (Apple Vision on a Mac, which is already there; RapidOCR on Windows/Linux, untested) finds the
name, the questions and the option lines; the X is **not** read as text: the box before each option is measured and counts as marked when it has clearly more ink than an empty one.
A box with only a little ink is flagged "marca duvidosa", never decided. A handwritten name can be misread by accents ("Nícolas"): check the names column.

**Explaining the mistakes**: add "...e explique por que a escolha de cada aluno está errada" and the sheet gets an `Explicações` tab: one worked solution per question, one explanation per
wrong option chosen (reused for every student who chose it), and "Não respondeu" for blanks. It is written by the local model, so it is a draft for you to check: an explanation that
names another option as correct, or that corrects itself in the middle, is replaced by "confira à mão". Small models get ENEM maths wrong, so the questions are worked out by a **reasoning model** when one is there: the engine asks Ollama what is installed
(`deepseek-r1:14b`, then `:8b`, then `:7b`) and uses the best one **that fits this computer's memory** (file size x 1.4 + 1.5 GB must be under the RAM: the 14B needs about 16 GB,
the 8B about 12 GB). With none installed, or too little memory, it uses the chat model and the plan says so. `LITEAGENT_EXPLAIN_MODEL` names one yourself. The installer offers it
(only on computers that can run it, with its own approval for the download). About 2.5 minutes for 20 exams on a 24 GB Mac.

### The plan comes first

Before doing a multi-step job (grading exams, making a document, using the browser) Chakmati shows what it is about to do, after having a look at what is there:

    Plano:
    1. Procurar a pasta «provas_escaneadas» em ~/Documents/Chakmati: achei 20 arquivos.
    2. Verificar como ler cada prova: 20 escaneados ou fotos: leitura por OCR.
    3. Ler o nome e a marcação de cada aluno (nas imagens, medindo o quadradinho de cada alternativa).
    4. Comparar com o gabarito 1E - 2B - 3B e calcular acertos e nota (1 por acerto), ...
    5. Resolver cada questão com modelo de raciocínio deepseek-r1:14b (instalado) e explicar o erro de cada aluno, ...
    6. Montar a planilha com fórmulas (abre no Numbers) e esperar a sua aprovação antes de salvar.

It is the first text of the reply (and stays in it); a single simple step ("abre o Spotify") gets none. The plan is made by code from the request and from a look at the folder, so it
also decides the tool (text or OCR) and the model; it says when something is missing (OCR not installed, no reasoning model).

**Loose requests** (files, folders, apps) get the same treatment from what the model already returned (no extra model call): the steps are shown in plain lines and **checked first** against the disk and the
policy, in order ("create a.txt, then copy it" is fine; "copy x.txt into a folder nobody creates" shows `⚠ cp (origem): não existe` in the plan). A file named without its extension ("o rascunho") is found; if the name
fits two files, or the request does not say which file, which app or which site, it asks instead of guessing; "apague tudo" is refused; "... para a lixeira" and "faça uma cópia do X" are read by rule, not by the model.
`scripts/bench_loose_requests.py` runs 24 such requests against the real model.

**What is read by rules, not by the model** (exact, instant, and the model gets these wrong now and then): the file names a command reads (`cat lista` finds `lista.txt`; a name that fits two files asks which);
"crie a pasta X", "liste os arquivos", "mostre o conteúdo de X", "renomeie X para Y", "copie X para Y", "baixe URL como Z", "abre o <app instalado>", "mande X para a lixeira", "faça uma cópia do X", "apague tudo" (refused);
the title and the topic of a document ("com o título ...", "sobre ..."); the search query of a browser task ("pesquise ..."); the key and the folder of an exam; and the sums, averages and totals row of a spreadsheet (written by code
when you ask for them and the model left them out). Anything with an "and then", an unusual name or an unknown word is still left to the model.
`scripts/simulate_exams.py OUT TRUTH.json 20` makes 20 filled-in copies to try it.

### The expanded window (desktop)

The panel has two shapes. **Small** (the card beside the robot): the conversation is a strip of two lines showing the latest words, every topic folds by its title, and **Ampliar** (or a click on the strip) gives the conversation the whole card and folds all the other topics (the choice is remembered; a question for you, like a password, opens it by itself).
**Expanded** (the arrows button in the header; the square button next to it goes to full screen; drag the edges to resize): three columns, each with its own scroll. On the left the topics (decisions, messages, agenda,
automations, recent notices); in the middle the whole conversation with the command line; on the right **Tela do Chakmati**: the live pictures of what the browser is doing (`ao vivo`), the current step with its caption and
address, and a strip of every step to go back to one. Each side can be minimized with the arrow in its corner (the left one to the left edge, the Tela do Chakmati to the right edge) and the conversation takes the room; a minimized side leaves a narrow strip with its arrow, the number of pending approvals on the left one and a red dot on the right one while the browser is working; the choice is remembered. Below 1000 px wide the page goes back to one column by itself. The screen shows the page as it is now, in a browser frame with its address, and each new picture fades in over the last one (no counters, no strip: it looks like a live view). In this window the character stands, smaller and without the approvals mark, above the conversation and the little one on the desktop steps aside. The pictures are the browser's, not your screen: the Chakmati never captures your desktop.

**It asks, it does not make things up.** When a page wants a user name, a password, a code or any detail the request did not give, the browser agent asks you in the conversation: an input appears under the answer (a masked one for the password) and what you type goes straight to the page. The answer is kept in memory only until it is typed, is never given to the language model, never written in the database, the captions or the pictures' notes, and the API accepts it only from the app's own window. A made-up value is refused by code, a password is never typed from text, the login button is not clicked with the password empty, and a login is never reported as done when the page says it failed. `{"action":"login"}` does the whole classic form by code (asks, fills both fields, sends). A site you name ("acesse meu instagram") is opened directly.

## Install wizard (desktop)

    cd desktop && npm run setup        # or: electron . --setup

Reads the computer (RAM, free disk, cores, system), says whether it meets the minimum, picks the chat model that fits
(`qwen3.5:0.8b` under ~8 GB, `qwen3.5:4b` up to ~16 GB, `qwen3.5:latest` above) and offers the optional pieces (better voice,
microphone, WhatsApp, animations, hiding from screen sharing). Nothing optional is ticked. Every download shows its source and
size and asks first; "Pular" (skip) is the default button. Needs Ollama running. WhatsApp is only recorded here: connect it later in
Settings > Integrations. The native installers (`.exe`, `.pkg`, `.deb`) will start this wizard with `--setup`.

## Installers (macOS, Windows, Ubuntu)

    cd desktop && npm install && npm run dist      # builds for the system you are on, into desktop/dist/

The installer carries the app, the engine's code and a pinned `uv` (its SHA-256 is checked at build time); the macOS
`.pkg` is about 135 MB, most of it Electron. On the first open the setup wizard checks the computer, then prepares the
engine with that `uv` (Python plus dependencies, about 190 MB) and installs only what you tick; each download asks
first. Voice and microphone add their Python packages (about 200 MB each, 230 MB together). WhatsApp is not offered in
the installed app yet.

The installers are **not signed**: Windows (SmartScreen) and macOS (Gatekeeper) warn on the first open. On macOS:
right-click the app and choose Open. Where things live (remove these folders to uninstall completely): the app's data
folder (`~/Library/Application Support/Chakmati`, `%APPDATA%\Chakmati`, `~/.config/Chakmati`), plus `~/.lite-agent`
(voice, WhatsApp and browser files; the folder keeps its old name so existing data is not orphaned) and the Ollama models.

`.github/workflows/build.yml` builds all of them on GitHub (manual, or on pull requests that touch `desktop/` or the engine).
Only the macOS arm64 build was checked by hand; the Windows and Ubuntu builds are untested until that workflow runs.

## Settings (env)

| Variable | Default |
|---|---|
| `LITEAGENT_OLLAMA_URL` | `http://127.0.0.1:11434` |
| `LITEAGENT_CHAT_MODEL` | `qwen3.5:latest` |
| `LITEAGENT_THINK` | `0` |
| `LITEAGENT_GATE_BACKEND` | `heuristic` (`laya` needs `uv sync --extra laya`) |
| `LITEAGENT_GATE_MIN_CONFIDENCE` | `0.6` |
| `LITEAGENT_DB_PATH` | `liteagent.db` |
| `LITEAGENT_RESEARCH_BACKEND` | `off` (`ddg` = DuckDuckGo HTML, `searxng` = a SearXNG instance) |
| `LITEAGENT_SEARXNG_URL` | `http://localhost:8080` |
| `LITEAGENT_RESEARCH_SCORER` | `keepall` (`laya` is opt-in) |
| `LITEAGENT_RESULT_CUTOFF` | `0.2` |
| `LITEAGENT_KEEP_ALIVE` | `30m` (empty = Ollama default, which unloads the model after 5 min idle) |
| `LITEAGENT_PRELOAD_MODEL` | `1`; loads the model at startup (first request ~4 s faster, ~6 GB RAM resident with the default model). `0` turns it off |
| `LITEAGENT_RESEARCH_MAX_TOKENS` | `200` (`0` = no cap) |
| `LITEAGENT_RESEARCH_CONCISE` | `1` (answers in at most 3 short sentences) |
| `LITEAGENT_FETCH_DEADLINE` | `2.0` seconds to wait for page downloads (`0` = wait for all); a site that hangs is dropped |
| `LITEAGENT_RESEARCH_MAX_PAGES` | `4` candidate pages downloaded per question |
| `LITEAGENT_RESEARCH_TARGET_PAGES` | `2`: stop waiting as soon as 2 pages downloaded successfully (`0` = wait for all) |
| `LITEAGENT_CALENDAR_BACKEND` | `off` (`auto` \| `macos` \| `ics`) |
| `LITEAGENT_CALENDAR_ICS_PATH` | `agenda.ics` |
| `LITEAGENT_CALENDAR_NAME` | empty = the system's default calendar for new events |
| `LITEAGENT_BROWSER_BACKEND` | `off` (`chrome`; needs `uv sync --extra browser`), plus `LITEAGENT_BROWSER_HEADLESS` (`1`), `LITEAGENT_BROWSER_PROFILE`, `LITEAGENT_BROWSER_FRAMES_DIR`, `LITEAGENT_BROWSER_MAX_STEPS` (`12`) |
| `LITEAGENT_EXPLAIN_MODEL` | empty = the chat model; a stronger model for working out exam questions, e.g. `deepseek-r1:14b` |
| `LITEAGENT_WHATSAPP_BACKEND` | `off` (`openwa`) |
| `LITEAGENT_OPENWA_URL` | `http://127.0.0.1:8081` |
| `LITEAGENT_OPENWA_API_KEY` | empty = read `~/.lite-agent/openwa/api_key.txt` (`LITEAGENT_OPENWA_API_KEY_FILE`) |
| `LITEAGENT_WHATSAPP_MAX_SENDS_PER_HOUR` | `20` |
| `LITEAGENT_CONTACT` | `https://github.com/gregsvieira`: added to the User-Agent (Wikipedia rejects anonymous bots); empty = none |

## Test

    uv run pytest

## Desktop: Chakmati, o assistente flutuante (Electron)

O Chakmati, um robozinho de lata com chapéu amarelo, fica sempre por cima das janelas. Quando algo acontece, ele escreve um balão em cima, embaixo ou ao lado
(o lado com mais espaço na tela): "Você recebeu uma nova mensagem de Maria Victoria". Clicar no Chakmati abre o painel com
o resumo, as ações para você aprovar ou recusar, mensagens não lidas, agenda de hoje, avisos recentes, atalhos e uma
caixa para dar ordens ao agente. Arraste o Chakmati para mudar de lugar.

Para funcionar é preciso: o **Ollama** aberto, com o modelo `qwen3.5:latest` (`ollama pull qwen3.5`). Depois:

```bash
cd desktop && npm install && npm start   # abre o Chakmati; ele inicia o motor sozinho se nenhum estiver rodando
```

**macOS e permissões (Agenda, Microfone):** o macOS entrega a permissão ao programa que abriu o processo. Abrindo com
`npm run abrir` (em vez de `npm start`), o Electron é esse programa e o macOS mostra o pedido com o texto do Chakmati; com
`npm start` o pedido vai para o Terminal. Antes de abrir, o app declara os motivos no `Info.plist` do Electron
(`desktop/scripts/prepare-electron.js`, executado sozinho pelo `npm start` e pelo `npm install`).

O motor também pode rodar sozinho, sem o app: `uv run python -m liteagent.main` (escuta em 127.0.0.1:8765). As integrações
(WhatsApp, agenda, pesquisa na internet) são ligadas em **Ajustes**; o WhatsApp precisa do OpenWA (`scripts/openwa.sh`).
O SearXNG local é opcional: sem ele a pesquisa usa o DuckDuckGo.

Atalhos: `Ctrl/⌘+Shift+Espaço` abre/fecha o painel; `Ctrl/⌘+Shift+H` oculta tudo na hora.

**Segurança:** as janelas não têm Node nem rede (CSP `default-src 'none'`); só o processo principal fala com o motor, e só
em loopback. Aprovar/recusar exige o cabeçalho `X-LiteAgent-UI` e id validado. Nenhum texto de terceiros vira HTML.

**Janela invisível na tela compartilhada:** "Esconder do compartilhamento" usa `setContentProtection`. Limites reais:
Windows funciona; macOS depende do app de captura (apps que usam ScreenCaptureKit podem ainda enxergar a janela);
Linux não tem suporte. Teste antes de depender disso:

```bash
cd desktop && LITEAGENT_DESKTOP_PROTECT_TEST=/tmp/prot ./node_modules/.bin/electron .
# gera unprotected.png e protected.png (exige permissão de Gravação de Tela ao terminal)
```

Também há o modo discreto (balões sem nomes) e `LITEAGENT_DESKTOP_SNAPSHOT=/pasta` para gerar imagens do visual.
