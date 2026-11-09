"""Attached files: only the extracted text is kept (never the original), under a random id, and it is swept after a few days."""

import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from chakmati.features.files import reader

ID = re.compile(r"^[0-9a-f]{32}$")
KEEP_SECONDS = 7 * 24 * 3600


@dataclass(frozen=True)
class Attachment:
    id: str
    name: str
    text: str

    @property
    def chars(self) -> int:
        return len(self.text)


class AttachmentStore:
    def __init__(self, directory: str, now=time.time):
        self._dir = Path(directory)
        self._now = now
        self._dir.mkdir(parents=True, exist_ok=True)
        try:
            self._dir.chmod(0o700)
        except OSError:
            pass
        self.sweep()

    def add(self, name: str, data: bytes) -> Attachment:
        name = reader.clean_name(name)
        text = reader.read_text(name, data)  # raises UnreadableFile
        attachment_id = uuid.uuid4().hex
        (self._dir / f"{attachment_id}.json").write_text(json.dumps({"name": name}), encoding="utf-8")
        (self._dir / f"{attachment_id}.txt").write_text(text, encoding="utf-8")
        return Attachment(attachment_id, name, text)

    def get(self, attachment_id: str) -> Attachment | None:
        if not ID.fullmatch(str(attachment_id)):
            return None
        try:
            meta = json.loads((self._dir / f"{attachment_id}.json").read_text(encoding="utf-8"))
            return Attachment(attachment_id, str(meta.get("name") or "arquivo"), (self._dir / f"{attachment_id}.txt").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def delete(self, attachment_id: str) -> bool:
        if not ID.fullmatch(str(attachment_id)):
            return False
        found = False
        for suffix in (".json", ".txt"):
            try:
                (self._dir / f"{attachment_id}{suffix}").unlink()
                found = True
            except OSError:
                pass
        return found

    def sweep(self) -> int:
        limit = self._now() - KEEP_SECONDS
        removed = 0
        for path in self._dir.glob("*"):
            try:
                if ID.fullmatch(path.stem) and path.suffix in (".json", ".txt") and path.stat().st_mtime < limit:
                    path.unlink()
                    removed += 1
            except OSError:
                pass
        return removed
