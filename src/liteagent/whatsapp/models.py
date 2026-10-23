import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

MAX_TEXT = 4000
# person (phone number), WhatsApp's newer "linked id", or group. Bots, newsletters and status are not valid recipients.
_RECIPIENT = re.compile(r"^[0-9A-Za-z._-]+@(?:c\.us|lid|g\.us)$")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")  # everything except tab and newline


@dataclass(frozen=True)
class Chat:
    id: str
    name: str
    is_group: bool
    unread: int
    ts: datetime | None
    phone: str | None = None

    def label(self) -> str:
        kind = " (grupo)" if self.is_group else ""
        number = f" +{self.phone}" if self.phone else ""
        return f"{self.name}{kind}{number}"


@dataclass(frozen=True)
class Message:
    id: str
    chat_id: str
    sender: str
    text: str
    ts: datetime
    from_me: bool
    kind: str = "chat"

    def display(self) -> str:
        """One line: time, sender, text. Media never shows its raw body, only a [type] marker."""
        body = " ".join(self.text.split())
        if self.kind != "chat":
            body = f"{body} [{self.kind}]".strip()
        return f"[{self.ts:%d/%m %H:%M}] {self.sender}: {body}"


@dataclass(frozen=True)
class Status:
    connected: bool
    state: str


@dataclass(frozen=True)
class Outgoing:
    """A message the user wants to send. Validated here so nothing malformed ever reaches the provider."""

    to: str
    text: str

    def __post_init__(self) -> None:
        if not _RECIPIENT.match(self.to):
            raise ValueError("recipient must be a person or group id (…@c.us, …@lid or …@g.us)")
        text = self.text.strip()
        if not text or len(text) > MAX_TEXT:
            raise ValueError(f"text must have 1-{MAX_TEXT} characters")
        if _CONTROL.search(text):
            raise ValueError("text contains control characters")
        object.__setattr__(self, "text", text)


class MessagingProvider(Protocol):
    async def status(self) -> Status: ...

    async def list_chats(self, unread_only: bool = False, limit: int = 50) -> list[Chat]: ...

    async def get_messages(self, chat_id: str, last: int = 20) -> list[Message]: ...

    async def send_text(self, chat_id: str, text: str) -> str: ...
