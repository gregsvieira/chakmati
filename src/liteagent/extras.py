"""Optional pieces of the engine. They are not installed by default, to keep the base install small:

    uv sync --extra voice     the enhanced voice (Piper) and voice notes for WhatsApp
    uv sync --extra listen    speech recognition (faster-whisper) for "talk to Chakmati"
    uv sync --extra documents Word (.docx), Excel (.xlsx) and PowerPoint (.pptx) files, which Pages, Numbers and Keynote open; and reading PDFs (grading exams)
    uv sync --extra ocr       reading scanned exams and phone photos (Apple Vision on a Mac, RapidOCR elsewhere)
    uv sync --extra browser   the browser agent (Playwright, drives the Chrome already installed)

Each piece imports its packages only when it is used, and says what to install when they are missing."""

import importlib.util

EXTRAS: dict[str, tuple[str, ...]] = {
    "voice": ("piper", "av"),
    "listen": ("faster_whisper", "av"),
    "browser": ("playwright",),
    "ocr": ("pypdfium2", "PIL"),
    "documents": ("docx", "openpyxl", "pptx", "pypdf"),
}


def available(extra: str) -> bool:
    """True when every package of the extra can be imported."""
    return all(importlib.util.find_spec(module) is not None for module in EXTRAS[extra])


def missing_message(extra: str, what: str) -> str:
    return f"{what} is not installed: run `uv sync --extra {extra}`"
