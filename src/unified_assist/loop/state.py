from __future__ import annotations

from dataclasses import dataclass, field

from unified_assist.messages.models import Message


@dataclass(slots=True)
class LoopState:
    messages: list[Message]
    turn_count: int = 1
    max_output_recovery_count: int = 0
    reactive_compaction_attempted: bool = False
    transition_reason: str = "start"
    prompt_cache: dict[str, str] = field(default_factory=dict)
