import uvicorn
from fastapi import FastAPI

from .api import create_app
from .config import Settings
from .engine import Engine
from .gate import build_gate
from .jobs import JobStore, Worker
from .llm import OllamaClient
from .loop.scorer import KeepAllScorer
from .loop.twostage import LayaRelevanceScorer
from .research.fetch import PageFetcher
from .research.search import DuckDuckGoHtmlBackend
from .research.searxng import SearxngBackend
from .research.tool import ResearchTool


def build_app(settings: Settings | None = None) -> FastAPI:
    s = settings or Settings.from_env()
    store = JobStore(s.db_path)
    llm = OllamaClient(s.ollama_url, s.chat_model, think=s.think)
    researcher = None
    if s.research_backend in {"ddg", "searxng"}:
        search = (
            SearxngBackend(s.searxng_url)
            if s.research_backend == "searxng"
            else DuckDuckGoHtmlBackend()
        )
        researcher = ResearchTool(
            search,
            PageFetcher(),
            llm,
            LayaRelevanceScorer() if s.research_scorer == "laya" else KeepAllScorer(),
            result_cutoff=s.result_cutoff,
        )
    engine = Engine(build_gate(s), llm, store, researcher=researcher)
    return create_app(engine, store, Worker(store, engine.run_job))


def main() -> None:
    # Loopback only: the engine is unauthenticated and must not be network-reachable.
    uvicorn.run(build_app(), host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
