import os
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    ollama_url: str = "http://127.0.0.1:11434"
    chat_model: str = "qwen3.5:latest"
    think: bool = False
    gate_backend: str = "heuristic"  # "heuristic" | "laya"
    gate_min_confidence: float = 0.6
    db_path: str = "liteagent.db"
    research_backend: str = "off"  # "off" | "ddg" | "searxng"
    searxng_url: str = "http://localhost:8080"
    result_cutoff: float = 0.2
    research_scorer: str = "keepall"  # "keepall" | "laya"
    keep_alive: str = ""  # Ollama keep_alive, e.g. "30m"; empty = Ollama default
    preload_model: bool = False
    research_max_tokens: int = 200
    research_concise: bool = True
    fetch_deadline: float = 3.0  # seconds to wait for the page downloads; 0 = wait for all

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        d = cls()
        return cls(
            ollama_url=env.get("LITEAGENT_OLLAMA_URL", d.ollama_url),
            chat_model=env.get("LITEAGENT_CHAT_MODEL", d.chat_model),
            think=env.get("LITEAGENT_THINK", "0").lower() in {"1", "true", "yes"},
            gate_backend=env.get("LITEAGENT_GATE_BACKEND", d.gate_backend),
            gate_min_confidence=float(
                env.get("LITEAGENT_GATE_MIN_CONFIDENCE", d.gate_min_confidence)
            ),
            db_path=env.get("LITEAGENT_DB_PATH", d.db_path),
            research_backend=env.get("LITEAGENT_RESEARCH_BACKEND", d.research_backend),
            searxng_url=env.get("LITEAGENT_SEARXNG_URL", d.searxng_url),
            result_cutoff=float(env.get("LITEAGENT_RESULT_CUTOFF", d.result_cutoff)),
            research_scorer=env.get("LITEAGENT_RESEARCH_SCORER", d.research_scorer),
            keep_alive=env.get("LITEAGENT_KEEP_ALIVE", d.keep_alive),
            preload_model=env.get("LITEAGENT_PRELOAD_MODEL", "0").lower() in {"1", "true", "yes"},
            research_max_tokens=int(env.get("LITEAGENT_RESEARCH_MAX_TOKENS", d.research_max_tokens)),
            research_concise=env.get("LITEAGENT_RESEARCH_CONCISE", "1").lower() in {"1", "true", "yes"},
            fetch_deadline=float(env.get("LITEAGENT_FETCH_DEADLINE", d.fetch_deadline)),
        )
