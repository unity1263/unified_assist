from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from unified_assist.runtime.events import EventBus
from unified_assist.runtime.cancellation import CancellationScope

if TYPE_CHECKING:
    from unified_assist.agents.registry import AgentRegistry
    from unified_assist.llm.base import ModelAdapter
    from unified_assist.memory.manager import MemoryManager
    from unified_assist.prompt.builder import PromptBuilder
    from unified_assist.skills.models import Skill
    from unified_assist.stability.token_budget import TokenBudget
    from unified_assist.stability.transcript_store import TranscriptStore
    from unified_assist.tools.executor import ToolExecutor


@dataclass(slots=True)
class RuntimeServices:
    model: "ModelAdapter"
    prompt_builder: "PromptBuilder"
    tool_executor: "ToolExecutor"
    memory_manager: "MemoryManager | None"
    skills: list["Skill"]
    transcript_store: "TranscriptStore | None"
    agent_registry: "AgentRegistry"
    token_budget: "TokenBudget | None" = None
    event_bus: EventBus = field(default_factory=EventBus)
    cancellation_scope: CancellationScope = field(default_factory=CancellationScope)
