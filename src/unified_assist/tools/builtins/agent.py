from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from unified_assist.agents.registry import AgentRegistry
from unified_assist.agents.runtime import AgentRuntime
from unified_assist.runtime.services import RuntimeServices
from unified_assist.tools.base import BaseTool, ToolContext, ToolResult


@dataclass(slots=True)
class AgentToolInput:
    prompt: str
    description: str
    agent_type: str | None = None
    include_parent_context: bool = False
    cwd: str | None = None
    max_turns: int | None = None


class AgentTool(BaseTool[AgentToolInput]):
    name = "spawn_agent"
    description = "Delegate bounded work to a child agent runtime"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "prompt": {"type": "string"},
                "description": {"type": "string"},
                "agent_type": {"type": "string"},
                "include_parent_context": {"type": "boolean"},
                "cwd": {"type": "string"},
                "max_turns": {"type": "integer", "minimum": 1},
            },
            "required": ["prompt", "description"],
            "additionalProperties": False,
        }

    def parse_input(self, raw_input: Mapping[str, Any]) -> AgentToolInput:
        prompt = raw_input.get("prompt")
        description = raw_input.get("description")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("prompt must be a non-empty string")
        if not isinstance(description, str) or not description.strip():
            raise ValueError("description must be a non-empty string")
        agent_type = raw_input.get("agent_type")
        if agent_type is not None and not isinstance(agent_type, str):
            raise ValueError("agent_type must be a string")
        cwd = raw_input.get("cwd")
        if cwd is not None and not isinstance(cwd, str):
            raise ValueError("cwd must be a string")
        max_turns = raw_input.get("max_turns")
        if max_turns is not None and (not isinstance(max_turns, int) or max_turns <= 0):
            raise ValueError("max_turns must be a positive integer")
        return AgentToolInput(
            prompt=prompt.strip(),
            description=description.strip(),
            agent_type=agent_type,
            include_parent_context=bool(raw_input.get("include_parent_context", False)),
            cwd=cwd,
            max_turns=max_turns,
        )

    async def call(self, parsed_input: AgentToolInput, context: ToolContext) -> ToolResult:
        services = context.metadata.get("runtime_services")
        if not isinstance(services, RuntimeServices):
            return ToolResult(content="runtime services unavailable for agent spawning", is_error=True)

        registry = services.agent_registry
        if not isinstance(registry, AgentRegistry):
            return ToolResult(content="agent registry unavailable", is_error=True)

        try:
            agent_definition = registry.resolve(parsed_input.agent_type)
        except KeyError as exc:
            return ToolResult(content=str(exc), is_error=True)

        if parsed_input.include_parent_context:
            agent_definition = type(agent_definition)(
                agent_type=agent_definition.agent_type,
                description=agent_definition.description,
                system_prompt=agent_definition.system_prompt,
                allowed_tools=agent_definition.allowed_tools,
                max_turns=agent_definition.max_turns,
                include_parent_context=True,
                model=agent_definition.model,
                allow_nested_agents=agent_definition.allow_nested_agents,
            )

        runtime = AgentRuntime(services)
        parent_messages = list(context.metadata.get("messages", []))
        child_cwd = Path(parsed_input.cwd).resolve() if parsed_input.cwd else context.cwd
        result = await runtime.run(
            agent_definition=agent_definition,
            task_prompt=parsed_input.prompt,
            parent_messages=parent_messages,
            parent_context=context,
            description=parsed_input.description,
            cwd=child_cwd,
            max_turns=parsed_input.max_turns,
        )
        return ToolResult(
            content=(
                f"Agent {result.agent_definition.agent_type} completed.\n"
                f"Transition: {result.state.transition_reason}\n"
                f"Result: {result.summary}"
            ),
            metadata={
                "agent_session_id": result.session_id,
                "agent_type": result.agent_definition.agent_type,
                "transition_reason": result.state.transition_reason,
            },
        )
