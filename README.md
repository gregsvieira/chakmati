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
| `LITEAGENT_KEEP_ALIVE` | empty = Ollama default (5 min); e.g. `30m` keeps the model in RAM longer |
| `LITEAGENT_PRELOAD_MODEL` | `0`; `1` loads the model at startup (first request ~4 s faster, ~6 GB RAM resident) |
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
