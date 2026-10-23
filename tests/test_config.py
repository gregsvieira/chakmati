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
            "LITEAGENT_CHAT_MODEL": "llama3.2:latest",
            "LITEAGENT_THINK": "1",
            "LITEAGENT_GATE_BACKEND": "laya",
            "LITEAGENT_GATE_MIN_CONFIDENCE": "0.8",
            "LITEAGENT_DB_PATH": "/tmp/x.db",
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
    s = Settings.from_env({"LITEAGENT_RESEARCH_BACKEND": "ddg", "LITEAGENT_RESULT_CUTOFF": "0.3"})
    assert (s.research_backend, s.result_cutoff) == ("ddg", 0.3)


def test_research_scorer_setting():
    assert Settings().research_scorer == "keepall"
    assert Settings.from_env({"LITEAGENT_RESEARCH_SCORER": "laya"}).research_scorer == "laya"


def test_searxng_url_setting():
    assert Settings().searxng_url == "http://localhost:8080"
    assert Settings.from_env({"LITEAGENT_SEARXNG_URL": "http://searx:8080"}).searxng_url == "http://searx:8080"
