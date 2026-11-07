import asyncio
import logging

import httpx
import uvicorn
from fastapi import FastAPI

from chakmati.features.browser.agent import BrowserAgent
from chakmati.features.browser.frames import FrameStore
from chakmati.features.browser.inputs import InputBroker
from chakmati.features.browser.session import PlaywrightSession
from chakmati.features.agenda.assistant import CalendarAssistant
from chakmati.features.agenda.factory import build_calendar
from chakmati.app.api import create_app
from chakmati.shared.approvals import ActionStore
from chakmati.features.automations.assistant import AutomationAssistant
from chakmati.features.automations.runner import AutomationRunner
from chakmati.features.automations.service import AutomationService
from chakmati.features.automations.store import AutomationStore
from chakmati.features.agenda.watcher import CalendarWatcher
from chakmati.features.automations.ticker import AutomationTicker
from chakmati.features.whatsapp.watcher import WhatsAppWatcher
from chakmati.shared.notices import ApprovalWatcher, NoticeBoard, Notifier
from chakmati.shared.config import Settings
from chakmati.shared import extras
from chakmati.app.engine import Engine
from chakmati.shared.gate import build_gate
from chakmati.shared.jobs import JobStore, Worker
from chakmati.shared.llm import OllamaClient, is_small_model
from chakmati.shared.models import ModelCatalog
from chakmati.features.research.loop.scorer import KeepAllScorer
from chakmati.features.research.loop.twostage import LayaRelevanceScorer
from chakmati.features.research.fetch import PageFetcher
from chakmati.features.research.search import DuckDuckGoHtmlBackend, build_user_agent
from chakmati.features.research.searxng import SearxngBackend
from chakmati.features.research.tool import ResearchTool
from chakmati.features.computer.assistant import ComputerAssistant
from chakmati.features.computer.service import ComputerService
from chakmati.features.home.api import HomeLink
from chakmati.features.home.docker import DockerHome
from chakmati.features.home.docker_setup import DockerSetup
from chakmati.features.home.install import HomeInstaller
from chakmati.features.home.assistant import HomeAssistantBot
from chakmati.features.home.auth import HomeAuth
from chakmati.features.home.client import HomeAssistantClient
from chakmati.features.home.service import HomeService
from chakmati.features.whatsapp.assistant import WhatsAppAssistant
from chakmati.shared.voice.stt import SpeechToText
from chakmati.shared.voice.tts import VoiceStore, VoiceSynth
from chakmati.features.whatsapp.factory import build_whatsapp, build_whatsapp_events


def build_app(settings: Settings | None = None) -> FastAPI:
    s = settings or Settings.from_env()
    store = JobStore(s.db_path)
    keep_alive = s.keep_alive or None
    llm = OllamaClient(s.ollama_url, s.chat_model, think=s.think, keep_alive=keep_alive)
    researcher = None
    search_backend = None
    if s.research_backend in {"ddg", "searxng"}:
        search = (
            SearxngBackend(s.searxng_url)
            if s.research_backend == "searxng"
            else DuckDuckGoHtmlBackend(user_agent=build_user_agent(s.contact))
        )
        search_backend = search
        research_llm = OllamaClient(
            s.ollama_url,
            s.chat_model,
            think=s.think,
            keep_alive=keep_alive,
            num_predict=s.research_max_tokens,
        )
        researcher = ResearchTool(
            search,
            PageFetcher(user_agent=build_user_agent(s.contact)),
            research_llm,
            LayaRelevanceScorer() if s.research_scorer == "laya" else KeepAllScorer(),
            result_cutoff=s.result_cutoff,
            concise=s.research_concise,
            fetch_deadline=s.fetch_deadline or None,
            max_pages=s.research_max_pages,
            target_pages=s.research_target_pages or None,
        )
    actions = ActionStore(s.db_path)  # one approval inbox shared by every integration
    calendar = build_calendar(s, actions)
    whatsapp = build_whatsapp(s, actions)
    voice = VoiceSynth(VoiceStore(s.voices_dir))
    automation_service = automation_runner = automation_assistant = None
    if whatsapp is not None:
        automation_store = AutomationStore(s.db_path)
        automation_service = AutomationService(automation_store, actions, voice, s.automations_dir, media_check=whatsapp.media_supported)
        automation_runner = AutomationRunner(automation_store, whatsapp, calendar=calendar, voice_dir=s.automations_dir)
        automation_assistant = AutomationAssistant(llm, automation_service, whatsapp)
    computer_service = ComputerService(s.workspace, actions)
    home_service = home_bot = home_link = None
    home_auth = HomeAuth(s.home_auth_file, s.home_token_file, s.home_url)
    home_client = HomeAssistantClient(auth=home_auth)
    home_http = httpx.AsyncClient(timeout=10.0)
    home_installer = HomeInstaller(DockerHome(s.home_config_dir), home_auth, home_http, s.home_docker_file, setup=DockerSetup(home_http))
    home_link = HomeLink(home_auth, home_client, installer=home_installer)  # the connect flow works even before it is connected, and even with the house switched off
    if s.home_backend == "homeassistant":
        home_service = HomeService(home_client, actions)  # not connected yet: it says so in words; connecting (Ajustes) works at once, with no restart
        home_bot = HomeAssistantBot(llm, home_service)
    frames = browser_agent = inputs = None
    if s.browser_backend == "chrome":
        frames = FrameStore(s.browser_frames_dir)
        inputs = InputBroker()
        browser_agent = BrowserAgent(llm, frames, lambda: PlaywrightSession(s.browser_profile, headless=s.browser_headless), max_steps=s.browser_max_steps,
                                    search=search_backend, ask=inputs.ask)
    catalog = ModelCatalog(s.ollama_url, configured=s.explain_model)  # which stronger model is installed (or named in CHAKMATI_EXPLAIN_MODEL), and fits
    worker_ref: list[Worker] = []
    engine = Engine(
        build_gate(s),
        llm,
        store,
        researcher=researcher,
        on_job_created=lambda: worker_ref[0].wake() if worker_ref else None,
        calendar_assistant=CalendarAssistant(llm, calendar) if calendar is not None else None,
        whatsapp_assistant=WhatsAppAssistant(llm, whatsapp) if whatsapp is not None else None,
        automation_assistant=automation_assistant,
        automation_service=automation_service,
        home_assistant=home_bot,
        home_service=home_service,
        computer_assistant=ComputerAssistant(llm, computer_service, gather=researcher.gather if researcher is not None else None, models=catalog, reasoning_for=lambda name: OllamaClient(s.ollama_url, name, think=True, keep_alive="5m", timeout=900), compact=is_small_model(s.chat_model)),
        computer_service=computer_service,
        browser_agent=browser_agent,
        personality=s.personality,
        pronouns=s.pronouns,
    )
    worker = Worker(store, engine.run_job, stream_handler=engine.run_job_stream)
    worker_ref.append(worker)
    board = NoticeBoard()
    events = build_whatsapp_events(s, board)
    watchers = []
    if whatsapp is not None:
        watchers.append(WhatsAppWatcher(whatsapp, board, s.whatsapp_poll_seconds, announce_connection=events is None,
                                      on_fresh=automation_runner.on_whatsapp_messages if automation_runner else None))
        if automation_runner is not None:
            watchers.append(AutomationTicker(automation_runner))
    if calendar is not None:
        watchers.append(CalendarWatcher(calendar, board, s.calendar_poll_seconds, s.calendar_lead_minutes))
    services = [x for x in (calendar, whatsapp, automation_service, home_service) if x is not None]
    if services:
        watchers.append(ApprovalWatcher([*services, computer_service], board))  # (the computer alone is not a reason to run the notifier)
    notifier = Notifier(watchers, background=[events.run] if events else []) if watchers and s.notices_enabled else None
    async def startup() -> None:
        """Once the engine is serving: the model is loaded into memory, and a Home Assistant that the Chakmati installed is switched on again."""
        jobs = ([llm.preload()] if s.preload_model else []) + ([home_installer.ensure_up()] if s.home_backend == "homeassistant" else [])
        await asyncio.gather(*jobs, return_exceptions=True)

    return create_app(
        engine,
        store,
        worker,
        board=board,
        notifier=notifier,
        stt=SpeechToText(s.stt_model) if s.stt_model != "off" and extras.available("listen") else None,
        tts=voice,
        automations=automation_service,
        home=home_service,
        computer=computer_service,
        frames=frames,
        inputs=inputs,
        home_link=home_link,
        on_startup=startup,
        calendar=calendar,
        whatsapp=whatsapp,
    )


def main() -> None:
    # Loopback only: the engine is unauthenticated and must not be network-reachable.
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")  # the engine's own notes (the browser's human check, ...) reach the log, not only uvicorn's
    uvicorn.run(build_app(), host="127.0.0.1", port=8765)


if __name__ == "__main__":
    main()
