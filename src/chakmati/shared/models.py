"""Which local models are installed, and which one to use for work that needs more thinking (an exam's questions, say).

Nothing here downloads anything. Ollama's own list says what is installed; the installer is where a stronger model gets added (with the
person's approval). A model is only picked when this computer has the memory for it: a 14B model on an 8 GB machine would swap and crawl,
and the standard chat model, slower to be right but able to run, is the better answer."""

import asyncio
import ctypes
import os
import subprocess
import sys
import time
from dataclasses import dataclass

import httpx

# Best first. These reason before they answer, which is what solving a maths question needs.
REASONING_PREFERENCE = ("deepseek-r1:14b", "deepseek-r1:8b", "deepseek-r1:7b")
HEADROOM = 1.4  # a model needs about its file size times this in memory, plus a fixed part for the system and the engine
FIXED_GB = 1.5


def total_ram_gb() -> float | None:
    """The computer's memory in GB, or None when it cannot be told."""
    try:
        if sys.platform == "darwin":
            return int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=3).stdout.strip()) / 1024**3
        if sys.platform.startswith("linux"):
            with open("/proc/meminfo", encoding="utf-8") as f:
                return int(f.readline().split()[1]) / 1024**2
        if sys.platform == "win32":
            class Status(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                            ("tpage", ctypes.c_ulonglong), ("apage", ctypes.c_ulonglong), ("tvirt", ctypes.c_ulonglong), ("avirt", ctypes.c_ulonglong),
                            ("ext", ctypes.c_ulonglong)]
            status = Status()
            status.length = ctypes.sizeof(Status)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
            return status.total / 1024**3
    except Exception:
        return None
    return None


@dataclass(frozen=True)
class Choice:
    """What will be used for the questions that need thinking, and what to tell the person about it."""
    model: str | None  # None = use the standard chat model
    why: str


class ModelCatalog:
    def __init__(self, ollama_url: str, configured: str = "", ram_gb: float | None = None, ttl: float = 30.0, transport: httpx.AsyncBaseTransport | None = None,
                 now=time.monotonic):
        self._url, self._configured, self._ttl, self._transport, self._now = ollama_url, configured.strip(), ttl, transport, now
        self._ram = ram_gb if ram_gb is not None else total_ram_gb()
        self._cache: tuple[float, dict[str, float]] | None = None
        self._lock = asyncio.Lock()

    async def installed(self) -> dict[str, float]:
        """{model name: size in GB} as Ollama lists them (empty when Ollama does not answer)."""
        async with self._lock:
            if self._cache and self._now() - self._cache[0] < self._ttl:
                return self._cache[1]
            try:
                async with httpx.AsyncClient(base_url=self._url, timeout=3.0, transport=self._transport) as http:
                    data = (await http.get("/api/tags")).json()
                found = {m["name"]: m.get("size", 0) / 1024**3 for m in data.get("models", []) if isinstance(m, dict) and "name" in m}
            except Exception:
                found = {}
            self._cache = (self._now(), found)
            return found

    def fits(self, size_gb: float) -> bool:
        return self._ram is None or size_gb * HEADROOM + FIXED_GB <= self._ram

    async def reasoning(self) -> Choice:
        have = await self.installed()
        wanted = [self._configured] if self._configured else [m for m in REASONING_PREFERENCE]
        skipped = None
        for name in wanted:
            match = next((n for n in have if n == name or (":" not in name and n.split(":")[0] == name)), None)
            if match is None and self._configured:
                match = name  # the person named it themselves: trust that it is there (Ollama will say if not)
            if match is None:
                continue
            size = have.get(match, 0.0)
            if self.fits(size):
                return Choice(match, f"modelo de raciocínio {match} (instalado)")
            skipped = match
        if skipped:
            return Choice(None, f"o modelo padrão (o {skipped} está instalado, mas este computador tem pouca memória para ele)")
        return Choice(None, "o modelo padrão (não há modelo de raciocínio instalado: as explicações podem errar mais; dá para instalar um pelo instalador)")
