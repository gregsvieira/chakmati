"""Builds the WhatsApp service from the settings."""

import os

from chakmati.shared.approvals import ActionStore
from chakmati.shared.config import Settings
from chakmati.shared.notices import NoticeBoard
from chakmati.features.whatsapp.events import WhatsAppEvents
from chakmati.features.whatsapp.openwa import OpenWAClient
from chakmati.features.whatsapp.webvoice import WebVoiceSender
from chakmati.features.whatsapp.service import WhatsAppService


def _api_key(settings: Settings) -> str:
    if settings.openwa_api_key:
        return settings.openwa_api_key
    try:
        with open(os.path.expanduser(settings.openwa_api_key_file), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""  # OpenWA started without --api-key: no header is sent


def build_whatsapp(settings: Settings, actions: ActionStore | None = None) -> WhatsAppService | None:
    backend = settings.whatsapp_backend
    if backend == "off":
        return None
    if backend != "openwa":
        raise ValueError(f"unknown whatsapp_backend {backend!r} (use off or openwa)")
    client = OpenWAClient(settings.openwa_url, _api_key(settings), voice=WebVoiceSender(settings.openwa_home))
    return WhatsAppService(
        client, actions or ActionStore(settings.db_path), max_sends_per_hour=settings.whatsapp_max_sends_per_hour
    )


def build_whatsapp_events(settings: Settings, board: NoticeBoard) -> WhatsAppEvents | None:
    """The live event listener for the same OpenWA server, or None when WhatsApp is off."""
    if settings.whatsapp_backend != "openwa":
        return None
    return WhatsAppEvents(settings.openwa_url, _api_key(settings), board)
