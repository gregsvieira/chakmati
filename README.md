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

## Test

    uv run pytest
