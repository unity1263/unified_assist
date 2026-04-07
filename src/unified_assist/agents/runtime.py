from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from unified_assist.agents.definitions import AgentDefinition
from unified_assist.agents.forking import build_fork_messages
from unified_assist.loop.agent_loop import AgentLoop
from unified_assist.loop.state import LoopState
from unified_assist.messages.models import AssistantMessage, Message, UserMessage
from unified_assist.prompt.builder import PromptBuilder
from unified_assist.runtime.services import RuntimeServices
from unified_assist.stability.transcript_store import TranscriptStore
from unified_assist.tools.base import ToolContext
from unified_assist.tools.executor import ToolExecutor


@dataclass(slots=True)
class AgentRunResult:
    agent_definition: AgentDefinition
    session_id: str
    state: LoopState
    summary: str


class AgentRuntime:
    def __init__(self, services: RuntimeServices) -> None:
        self.services = services

    async def run(
        self,
        *,
        agent_definition: AgentDefinition,
        task_prompt: str,
        parent_messages: list[Message],
        parent_context: ToolContext,
        description: str = "",
        cwd: Path | None = None,
        max_turns: int | None = None,
    ) -> AgentRunResult:
        child_registry = self.services.tool_executor.registry.subset(agent_definition.allowed_tools)
        if not agent_definition.allow_nested_agents:
            child_registry = child_registry.subset(
                [
                    name
                    for name in child_registry.names()
                    if name not in {"spawn_agent", "Agent", "Task"}
                ]
            )
        child_executor = ToolExecutor(child_registry, self.services.tool_executor.result_store)
        child_prompt_builder = PromptBuilder(
            base_role=agent_definition.system_prompt,
            operating_rules=self.services.prompt_builder.operating_rules,
        )
        child_cwd = Path(cwd or parent_context.cwd)
        child_context = parent_context.snapshot(
            cwd=child_cwd,
            metadata_updates={
                "parent_agent_type": agent_definition.agent_type,
            },
        )

        child_messages = (
            build_fork_messages(parent_messages, task_prompt)
            if agent_definition.include_parent_context
            else [UserMessage(content=task_prompt)]
        )
        child_loop = AgentLoop(
            model=self.services.model,
            prompt_builder=child_prompt_builder,
            tool_executor=child_executor,
            tool_context=child_context,
            memory_manager=self.services.memory_manager,
            skills=self.services.skills,
            max_turns=max_turns or agent_definition.max_turns,
            token_budget=self.services.token_budget,
        )
        session_id = f"agent-{agent_definition.agent_type}-{uuid4().hex[:8]}"
        self.services.event_bus.emit(
            "agent_started",
            agent_type=agent_definition.agent_type,
            session_id=session_id,
            description=description,
        )
        state = await child_loop.run(child_messages)
        summary = self._summarize_state(state)
        self.services.event_bus.emit(
            "agent_completed",
            agent_type=agent_definition.agent_type,
            session_id=session_id,
            transition_reason=state.transition_reason,
        )

        if self.services.transcript_store is not None:
            self.services.transcript_store.append_messages(session_id, state.messages)

        return AgentRunResult(
            agent_definition=agent_definition,
            session_id=session_id,
            state=state,
            summary=summary,
        )

    def _summarize_state(self, state: LoopState) -> str:
        for message in reversed(state.messages):
            if isinstance(message, AssistantMessage) and message.text:
                return message.text
        return f"Agent finished with transition: {state.transition_reason}"
