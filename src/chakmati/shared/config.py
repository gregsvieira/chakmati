import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from chakmati.shared.migrate import data_dir


def _data(*parts: str):
    """A path inside the data folder, worked out when the settings are made (after the old folder was moved, if it had to be)."""
    return field(default_factory=lambda: os.path.join(data_dir(), *parts))


class _Env:
    """The environment, read by the new name first (CHAKMATI_X) and by the old one (LITEAGENT_X) when the new is not set: an engine started
    before the rename keeps working."""

    def __init__(self, env: Mapping[str, str]):
        self._env = env

    def get(self, key: str, default=None):
        if key in self._env:
            return self._env[key]
        legacy = key.replace("CHAKMATI_", "LITEAGENT_", 1)
        return self._env.get(legacy, default)


@dataclass(frozen=True)
class Settings:
    ollama_url: str = "http://127.0.0.1:11434"
    chat_model: str = "qwen3.5:latest"
    think: bool = False
    cloud_provider: str = ""  # "" (only the local model) | "anthropic" | "openai": the paid AI the person connected; it is used first, the local model when its limit is over
    cloud_api_key: str = ""
    cloud_model: str = ""
    local_model: bool = True  # False = the person chose to run only on the paid AI (no local model behind it)
    explain_model: str = ""  # a stronger model for working out the questions of an exam (empty = the chat model); e.g. deepseek-r1:14b, which solved all three ENEM questions
    gate_backend: str = "heuristic"  # "heuristic" | "laya"
    gate_min_confidence: float = 0.6
    db_path: str = "liteagent.db"
    research_backend: str = "off"  # "off" | "ddg" | "searxng"
    searxng_url: str = "http://localhost:8080"
    result_cutoff: float = 0.2
    research_scorer: str = "keepall"  # "keepall" | "laya"
    keep_alive: str = "30m"  # Ollama keep_alive, e.g. "30m"; empty = Ollama default (unloads after 5 min idle)
    preload_model: bool = True
    research_max_tokens: int = 200
    research_concise: bool = True
    fetch_deadline: float = 2.0  # seconds to wait for the page downloads; 0 = wait for all
    research_max_pages: int = 4
    research_target_pages: int = 2  # stop waiting once this many pages succeeded; 0 = wait for all
    # Put in the User-Agent: Wikipedia answers 403 to anonymous bots. Replace with the project's own
    # URL once it is published, or set CHAKMATI_CONTACT (empty = send no contact).
    calendar_backend: str = "off"  # "off" | "auto" | "macos" | "ics"
    calendar_ics_path: str = "agenda.ics"
    calendar_name: str = ""  # calendar that new events go to (empty = the system default)
    whatsapp_backend: str = "off"  # "off" | "openwa"
    openwa_url: str = "http://127.0.0.1:8081"
    embed_model: str = ""  # an Ollama embedding model (e.g. nomic-embed-text) that also matches the MEANING of a question to the pieces of an attached file; empty = words only (lighter)
    attachments_dir: str = _data("attachments")  # the text of files attached to the conversation (swept after a week)
    workspace: str = os.path.expanduser("~/Documents/Chakmati")  # the only folder where the agent creates files
    openwa_home: str = _data("openwa")  # where OpenWA is installed (its browser is used for voice notes)
    browser_backend: str = "off"  # "off" | "chrome" (a visible Chrome driven with Playwright; needs `uv sync --extra browser`)
    browser_profile: str = _data("browser")  # the agent's own Chrome profile (never the person's)
    browser_frames_dir: str = _data("frames")  # the screenshot of every step of a browser job
    browser_max_steps: int = 12
    browser_headless: bool = True  # no Chrome window for the person; the screenshots are the view. False = watch it work
    home_backend: str = "off"  # "off" | "homeassistant" (also the way to reach Alexa-compatible devices)
    home_url: str = "http://homeassistant.local:8123"
    home_token_file: str = _data("home_token.txt")  # the older way: a long-lived token pasted by hand
    home_config_dir: str = _data("homeassistant")  # where the Home Assistant the Chakmati installed keeps its settings
    home_docker_file: str = _data("home_docker.json")  # says the Chakmati installed it (so it switches it on at start)
    home_auth_file: str = _data("home_auth.json")  # what the connect flow in Ajustes writes (address and renewable tokens)
    openwa_api_key: str = ""
    openwa_api_key_file: str = _data("openwa", "api_key.txt")
    whatsapp_max_sends_per_hour: int = 20
    notices_enabled: bool = True
    automations_dir: str = _data("automations")  # recordings of voice automations
    voices_dir: str = _data("voices")  # where the downloaded enhanced voice lives
    stt_language: str = "pt"  # the language of the microphone ("pt", or "auto" to let the model guess)
    stt_model: str = "base"  # faster-whisper model for "listen and speak"; "off" disables it
    whatsapp_poll_seconds: float = 10.0
    calendar_poll_seconds: float = 60.0
    calendar_lead_minutes: int = 10
    contact: str = "https://github.com/gregsvieira"
    pronouns: str = "none"  # how the person is addressed: none | ele | ela | elu (changeable at runtime: PUT /pronouns)
    personality: str = "padrao"  # the regional way of speaking: padrao | carioca | paulista | gaucho | nordestino | mineiro (changeable at runtime: PUT /personality)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = _Env(os.environ if env is None else env)
        d = cls()
        return cls(
            ollama_url=env.get("CHAKMATI_OLLAMA_URL", d.ollama_url),
            chat_model=env.get("CHAKMATI_CHAT_MODEL", d.chat_model),
            explain_model=env.get("CHAKMATI_EXPLAIN_MODEL", d.explain_model),
            think=env.get("CHAKMATI_THINK", "0").lower() in {"1", "true", "yes"},
            cloud_provider=env.get("CHAKMATI_CLOUD_PROVIDER", d.cloud_provider),
            cloud_api_key=env.get("CHAKMATI_CLOUD_API_KEY", d.cloud_api_key),
            cloud_model=env.get("CHAKMATI_CLOUD_MODEL", d.cloud_model),
            local_model=env.get("CHAKMATI_LOCAL_MODEL", "1").lower() in {"1", "true", "yes"},
            gate_backend=env.get("CHAKMATI_GATE_BACKEND", d.gate_backend),
            gate_min_confidence=float(
                env.get("CHAKMATI_GATE_MIN_CONFIDENCE", d.gate_min_confidence)
            ),
            db_path=env.get("CHAKMATI_DB_PATH", d.db_path),
            research_backend=env.get("CHAKMATI_RESEARCH_BACKEND", d.research_backend),
            searxng_url=env.get("CHAKMATI_SEARXNG_URL", d.searxng_url),
            result_cutoff=float(env.get("CHAKMATI_RESULT_CUTOFF", d.result_cutoff)),
            research_scorer=env.get("CHAKMATI_RESEARCH_SCORER", d.research_scorer),
            keep_alive=env.get("CHAKMATI_KEEP_ALIVE", d.keep_alive),
            preload_model=env.get("CHAKMATI_PRELOAD_MODEL", "1" if d.preload_model else "0").lower() in {"1", "true", "yes"},
            research_max_tokens=int(env.get("CHAKMATI_RESEARCH_MAX_TOKENS", d.research_max_tokens)),
            research_concise=env.get("CHAKMATI_RESEARCH_CONCISE", "1").lower() in {"1", "true", "yes"},
            fetch_deadline=float(env.get("CHAKMATI_FETCH_DEADLINE", d.fetch_deadline)),
            research_max_pages=int(env.get("CHAKMATI_RESEARCH_MAX_PAGES", d.research_max_pages)),
            research_target_pages=int(env.get("CHAKMATI_RESEARCH_TARGET_PAGES", d.research_target_pages)),
            calendar_backend=env.get("CHAKMATI_CALENDAR_BACKEND", d.calendar_backend),
            calendar_ics_path=env.get("CHAKMATI_CALENDAR_ICS_PATH", d.calendar_ics_path),
            calendar_name=env.get("CHAKMATI_CALENDAR_NAME", d.calendar_name),
            whatsapp_backend=env.get("CHAKMATI_WHATSAPP_BACKEND", d.whatsapp_backend),
            openwa_url=env.get("CHAKMATI_OPENWA_URL", d.openwa_url),
            embed_model=env.get("CHAKMATI_EMBED_MODEL", d.embed_model),
            attachments_dir=os.path.expanduser(env.get("CHAKMATI_ATTACHMENTS_DIR", d.attachments_dir)),
            workspace=os.path.expanduser(env.get("CHAKMATI_WORKSPACE", d.workspace)),
            openwa_home=os.path.expanduser(env.get("CHAKMATI_OPENWA_HOME", d.openwa_home)),
            browser_backend=env.get("CHAKMATI_BROWSER_BACKEND", d.browser_backend),
            browser_profile=os.path.expanduser(env.get("CHAKMATI_BROWSER_PROFILE", d.browser_profile)),
            browser_frames_dir=os.path.expanduser(env.get("CHAKMATI_BROWSER_FRAMES_DIR", d.browser_frames_dir)),
            browser_headless=env.get("CHAKMATI_BROWSER_HEADLESS", "1" if d.browser_headless else "0").lower() in {"1", "true", "yes"},
            browser_max_steps=int(env.get("CHAKMATI_BROWSER_MAX_STEPS", d.browser_max_steps)),
            home_backend=env.get("CHAKMATI_HOME_BACKEND", d.home_backend),
            home_url=env.get("CHAKMATI_HOME_URL", d.home_url),
            home_token_file=os.path.expanduser(env.get("CHAKMATI_HOME_TOKEN_FILE", d.home_token_file)),
            home_auth_file=os.path.expanduser(env.get("CHAKMATI_HOME_AUTH_FILE", d.home_auth_file)),
            home_config_dir=os.path.expanduser(env.get("CHAKMATI_HOME_CONFIG_DIR", d.home_config_dir)),
            home_docker_file=os.path.expanduser(env.get("CHAKMATI_HOME_DOCKER_FILE", d.home_docker_file)),
            openwa_api_key=env.get("CHAKMATI_OPENWA_API_KEY", d.openwa_api_key),
            openwa_api_key_file=env.get("CHAKMATI_OPENWA_API_KEY_FILE", d.openwa_api_key_file),
            whatsapp_max_sends_per_hour=int(env.get("CHAKMATI_WHATSAPP_MAX_SENDS_PER_HOUR", d.whatsapp_max_sends_per_hour)),
            voices_dir=os.path.expanduser(env.get("CHAKMATI_VOICES_DIR", d.voices_dir)),
            automations_dir=os.path.expanduser(env.get("CHAKMATI_AUTOMATIONS_DIR", d.automations_dir)),
            stt_model=env.get("CHAKMATI_STT_MODEL", d.stt_model),
            stt_language=env.get("CHAKMATI_STT_LANGUAGE", d.stt_language),
            notices_enabled=env.get("CHAKMATI_NOTICES", "1").lower() in {"1", "true", "yes"},
            whatsapp_poll_seconds=float(env.get("CHAKMATI_WHATSAPP_POLL_SECONDS", d.whatsapp_poll_seconds)),
            calendar_poll_seconds=float(env.get("CHAKMATI_CALENDAR_POLL_SECONDS", d.calendar_poll_seconds)),
            calendar_lead_minutes=int(env.get("CHAKMATI_CALENDAR_LEAD_MINUTES", d.calendar_lead_minutes)),
            contact=env.get("CHAKMATI_CONTACT", d.contact),
            personality=env.get("CHAKMATI_PERSONALITY", d.personality),
            pronouns=env.get("CHAKMATI_PRONOUNS", d.pronouns),
        )
