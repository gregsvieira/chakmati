"""The screenshots of a browser job, one per step, kept on disk so the UI can show them as they appear (and a client that
connects late still gets all of them). Frames are JPEGs named by their step number; `meta.jsonl` has one line per frame."""

import json
import re
import shutil
import time
from pathlib import Path

_JOB_ID = re.compile(r"^[0-9a-f]{32}$")
KEEP_JOBS = 20  # older jobs' frames are deleted so the folder never grows without bound


class FrameStore:
    def __init__(self, root: str | Path):
        self._root = Path(root).expanduser()

    def _dir(self, job_id: str) -> Path:
        if not _JOB_ID.match(job_id):
            raise ValueError("invalid job id")
        return self._root / job_id

    def add(self, job_id: str, jpeg: bytes, url: str, title: str, note: str) -> int:
        folder = self._dir(job_id)
        folder.mkdir(parents=True, exist_ok=True)
        step = len(self.list(job_id)) + 1
        (folder / f"{step}.jpg").write_bytes(jpeg)
        with (folder / "meta.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"step": step, "url": url, "title": title, "note": note}, ensure_ascii=False) + "\n")
        self._prune(keep=job_id)
        return step

    def list(self, job_id: str) -> list[dict]:
        meta = self._dir(job_id) / "meta.jsonl"
        if not meta.is_file():
            return []
        return [json.loads(line) for line in meta.read_text(encoding="utf-8").splitlines() if line.strip()]

    def path(self, job_id: str, step: int) -> Path | None:
        p = self._dir(job_id) / f"{int(step)}.jpg"
        return p if p.is_file() else None

    def _prune(self, keep: str) -> None:
        folders = sorted((p for p in self._root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in folders[KEEP_JOBS:]:
            if old.name != keep:
                shutil.rmtree(old, ignore_errors=True)
