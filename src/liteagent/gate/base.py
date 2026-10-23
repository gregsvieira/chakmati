from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class Route(str, Enum):
    CHAT = "chat"
    RESEARCH = "research"
    TASK = "task"

    @property
    def is_slow(self) -> bool:
        return self is not Route.CHAT


@dataclass(frozen=True)
class GateResult:
    route: Route
    confidence: float
    source: str


class Gate(Protocol):
    def classify(self, text: str) -> GateResult: ...
