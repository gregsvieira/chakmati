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
    research_backend: str = "off"  # "off" | "ddg"
    result_cutoff: float = 0.2

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
            result_cutoff=float(env.get("LITEAGENT_RESULT_CUTOFF", d.result_cutoff)),
        )
