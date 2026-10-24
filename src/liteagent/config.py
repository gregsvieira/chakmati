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
    fetch_deadline: float = 2.0  # seconds to wait for the page downloads; 0 = wait for all
    research_max_pages: int = 4
    research_target_pages: int = 2  # stop waiting once this many pages succeeded; 0 = wait for all
    # Put in the User-Agent: Wikipedia answers 403 to anonymous bots. Replace with the project's own
    # URL once it is published, or set LITEAGENT_CONTACT (empty = send no contact).
    calendar_backend: str = "off"  # "off" | "auto" | "macos" | "ics"
    calendar_ics_path: str = "agenda.ics"
    calendar_name: str = ""  # calendar that new events go to (empty = the system default)
    whatsapp_backend: str = "off"  # "off" | "openwa"
    openwa_url: str = "http://127.0.0.1:8081"
    workspace: str = os.path.expanduser("~/Documents/Chakmati")  # the only folder where the agent creates files
    openwa_home: str = os.path.expanduser("~/.lite-agent/openwa")  # where OpenWA is installed (its browser is used for voice notes)
    home_backend: str = "off"  # "off" | "homeassistant" (also the way to reach Alexa-compatible devices)
    home_url: str = "http://homeassistant.local:8123"
    home_token_file: str = os.path.expanduser("~/.lite-agent/home_token.txt")
    openwa_api_key: str = ""
    openwa_api_key_file: str = os.path.expanduser("~/.lite-agent/openwa/api_key.txt")
    whatsapp_max_sends_per_hour: int = 20
    notices_enabled: bool = True
    automations_dir: str = os.path.expanduser("~/.lite-agent/automations")  # recordings of voice automations
    voices_dir: str = os.path.expanduser("~/.lite-agent/voices")  # where the downloaded enhanced voice lives
    stt_model: str = "base"  # faster-whisper model for "listen and speak"; "off" disables it
    whatsapp_poll_seconds: float = 10.0
    calendar_poll_seconds: float = 60.0
    calendar_lead_minutes: int = 10
    contact: str = "https://github.com/gregsvieira"

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
            research_max_pages=int(env.get("LITEAGENT_RESEARCH_MAX_PAGES", d.research_max_pages)),
            research_target_pages=int(env.get("LITEAGENT_RESEARCH_TARGET_PAGES", d.research_target_pages)),
            calendar_backend=env.get("LITEAGENT_CALENDAR_BACKEND", d.calendar_backend),
            calendar_ics_path=env.get("LITEAGENT_CALENDAR_ICS_PATH", d.calendar_ics_path),
            calendar_name=env.get("LITEAGENT_CALENDAR_NAME", d.calendar_name),
            whatsapp_backend=env.get("LITEAGENT_WHATSAPP_BACKEND", d.whatsapp_backend),
            openwa_url=env.get("LITEAGENT_OPENWA_URL", d.openwa_url),
            workspace=os.path.expanduser(env.get("LITEAGENT_WORKSPACE", d.workspace)),
            openwa_home=os.path.expanduser(env.get("LITEAGENT_OPENWA_HOME", d.openwa_home)),
            home_backend=env.get("LITEAGENT_HOME_BACKEND", d.home_backend),
            home_url=env.get("LITEAGENT_HOME_URL", d.home_url),
            home_token_file=os.path.expanduser(env.get("LITEAGENT_HOME_TOKEN_FILE", d.home_token_file)),
            openwa_api_key=env.get("LITEAGENT_OPENWA_API_KEY", d.openwa_api_key),
            openwa_api_key_file=env.get("LITEAGENT_OPENWA_API_KEY_FILE", d.openwa_api_key_file),
            whatsapp_max_sends_per_hour=int(env.get("LITEAGENT_WHATSAPP_MAX_SENDS_PER_HOUR", d.whatsapp_max_sends_per_hour)),
            voices_dir=os.path.expanduser(env.get("LITEAGENT_VOICES_DIR", d.voices_dir)),
            automations_dir=os.path.expanduser(env.get("LITEAGENT_AUTOMATIONS_DIR", d.automations_dir)),
            stt_model=env.get("LITEAGENT_STT_MODEL", d.stt_model),
            notices_enabled=env.get("LITEAGENT_NOTICES", "1").lower() in {"1", "true", "yes"},
            whatsapp_poll_seconds=float(env.get("LITEAGENT_WHATSAPP_POLL_SECONDS", d.whatsapp_poll_seconds)),
            calendar_poll_seconds=float(env.get("LITEAGENT_CALENDAR_POLL_SECONDS", d.calendar_poll_seconds)),
            calendar_lead_minutes=int(env.get("LITEAGENT_CALENDAR_LEAD_MINUTES", d.calendar_lead_minutes)),
            contact=env.get("LITEAGENT_CONTACT", d.contact),
        )
