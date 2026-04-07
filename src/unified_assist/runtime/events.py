from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    kind: str
    payload: dict[str, Any] = field(default_factory=dict)


class EventBus:
    def __init__(self) -> None:
        self.events: list[RuntimeEvent] = []

    def emit(self, kind: str, **payload: Any) -> None:
        self.events.append(RuntimeEvent(kind=kind, payload=payload))
