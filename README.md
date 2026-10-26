# lite-agent

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
(voice and WhatsApp files) and the Ollama models.

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
