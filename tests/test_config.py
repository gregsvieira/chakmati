from liteagent.config import Settings


def test_defaults():
    s = Settings()
    assert s.ollama_url == "http://127.0.0.1:11434"
    assert s.think is False
    assert s.gate_backend == "heuristic"
    assert s.gate_min_confidence == 0.6


def test_from_env_overrides():
    s = Settings.from_env(
        {
            "CHAKMATI_CHAT_MODEL": "llama3.2:latest",
            "CHAKMATI_THINK": "1",
            "CHAKMATI_GATE_BACKEND": "laya",
            "CHAKMATI_GATE_MIN_CONFIDENCE": "0.8",
            "CHAKMATI_DB_PATH": "/tmp/x.db",
        }
    )
    assert s.chat_model == "llama3.2:latest"
    assert s.think is True
    assert s.gate_backend == "laya"
    assert s.gate_min_confidence == 0.8
    assert s.db_path == "/tmp/x.db"


def test_from_env_empty_uses_defaults():
    assert Settings.from_env({}) == Settings()


def test_research_settings():
    d = Settings()
    assert (d.research_backend, d.result_cutoff) == ("off", 0.2)
    s = Settings.from_env({"CHAKMATI_RESEARCH_BACKEND": "ddg", "CHAKMATI_RESULT_CUTOFF": "0.3"})
    assert (s.research_backend, s.result_cutoff) == ("ddg", 0.3)


def test_research_scorer_setting():
    assert Settings().research_scorer == "keepall"
    assert Settings.from_env({"CHAKMATI_RESEARCH_SCORER": "laya"}).research_scorer == "laya"


def test_searxng_url_setting():
    assert Settings().searxng_url == "http://localhost:8080"
    assert Settings.from_env({"CHAKMATI_SEARXNG_URL": "http://searx:8080"}).searxng_url == "http://searx:8080"


def test_speed_settings():
    d = Settings()
    assert (d.keep_alive, d.preload_model, d.research_max_tokens, d.research_concise) == ("30m", True, 200, True)
    s = Settings.from_env(
        {
            "CHAKMATI_KEEP_ALIVE": "30m",
            "CHAKMATI_PRELOAD_MODEL": "1",
            "CHAKMATI_RESEARCH_MAX_TOKENS": "120",
            "CHAKMATI_RESEARCH_CONCISE": "0",
        }
    )
    assert (s.keep_alive, s.preload_model, s.research_max_tokens, s.research_concise) == ("30m", True, 120, False)


def test_preload_and_keep_alive_can_be_turned_off():
    s = Settings.from_env({"CHAKMATI_KEEP_ALIVE": "", "CHAKMATI_PRELOAD_MODEL": "0"})
    assert (s.keep_alive, s.preload_model) == ("", False)


def test_fetch_deadline_setting():
    assert Settings().fetch_deadline == 2.0
    assert Settings.from_env({"CHAKMATI_FETCH_DEADLINE": "0"}).fetch_deadline == 0.0


def test_research_max_pages_setting():
    assert Settings().research_max_pages == 4
    assert Settings.from_env({"CHAKMATI_RESEARCH_MAX_PAGES": "2"}).research_max_pages == 2


def test_contact_and_target_pages_settings():
    assert Settings().contact == "https://github.com/gregsvieira"
    assert Settings().research_target_pages == 2
    s = Settings.from_env({"CHAKMATI_CONTACT": "https://example.org/me", "CHAKMATI_RESEARCH_TARGET_PAGES": "2"})
    assert (s.contact, s.research_target_pages) == ("https://example.org/me", 2)


def test_calendar_settings_are_off_by_default():
    d = Settings()
    assert (d.calendar_backend, d.calendar_ics_path, d.calendar_name) == ("off", "agenda.ics", "")
    s = Settings.from_env({"CHAKMATI_CALENDAR_BACKEND": "ics", "CHAKMATI_CALENDAR_ICS_PATH": "/tmp/a.ics",
                           "CHAKMATI_CALENDAR_NAME": "Trabalho"})
    assert (s.calendar_backend, s.calendar_ics_path, s.calendar_name) == ("ics", "/tmp/a.ics", "Trabalho")


def test_whatsapp_settings_are_off_by_default():
    d = Settings()
    assert (d.whatsapp_backend, d.openwa_url, d.openwa_api_key, d.whatsapp_max_sends_per_hour) == (
        "off", "http://127.0.0.1:8081", "", 20)
    assert d.openwa_api_key_file.endswith("/.lite-agent/openwa/api_key.txt")
    s = Settings.from_env({"CHAKMATI_WHATSAPP_BACKEND": "openwa", "CHAKMATI_OPENWA_URL": "http://h:1",
                           "CHAKMATI_OPENWA_API_KEY": "k", "CHAKMATI_WHATSAPP_MAX_SENDS_PER_HOUR": "5"})
    assert (s.whatsapp_backend, s.openwa_url, s.openwa_api_key, s.whatsapp_max_sends_per_hour) == ("openwa", "http://h:1", "k", 5)


def test_notice_settings():
    d = Settings()
    assert (d.notices_enabled, d.whatsapp_poll_seconds, d.calendar_poll_seconds, d.calendar_lead_minutes) == (True, 10.0, 60.0, 10)
    s = Settings.from_env({"CHAKMATI_NOTICES": "0", "CHAKMATI_WHATSAPP_POLL_SECONDS": "5",
                           "CHAKMATI_CALENDAR_POLL_SECONDS": "30", "CHAKMATI_CALENDAR_LEAD_MINUTES": "15"})
    assert (s.notices_enabled, s.whatsapp_poll_seconds, s.calendar_poll_seconds, s.calendar_lead_minutes) == (False, 5.0, 30.0, 15)


def test_stt_model_setting():
    assert Settings.from_env({}).stt_model == "base"
    assert Settings.from_env({"CHAKMATI_STT_MODEL": "off"}).stt_model == "off"


def test_the_browser_is_headless_unless_asked_otherwise():
    assert Settings.from_env({}).browser_headless is True
    assert Settings.from_env({"CHAKMATI_BROWSER_HEADLESS": "0"}).browser_headless is False


def test_the_old_names_still_work_when_the_new_ones_are_not_set():
    s = Settings.from_env({"LITEAGENT_CHAT_MODEL": "old:1b", "LITEAGENT_BROWSER_BACKEND": "chrome"})
    assert s.chat_model == "old:1b" and s.browser_backend == "chrome"


def test_the_new_name_wins_over_the_old_one():
    s = Settings.from_env({"CHAKMATI_CHAT_MODEL": "new:4b", "LITEAGENT_CHAT_MODEL": "old:1b"})
    assert s.chat_model == "new:4b"
