from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from unified_assist.tools.base import BaseTool, ToolContext, ToolResult


@dataclass(slots=True)
class ThinkInput:
    thought: str


class ThinkTool(BaseTool[ThinkInput]):
    name = "think"
    description = "Externalize a short reasoning note"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "thought": {"type": "string"},
            },
            "required": ["thought"],
            "additionalProperties": False,
        }

    def parse_input(self, raw_input: Mapping[str, Any]) -> ThinkInput:
        thought = raw_input.get("thought")
        if not isinstance(thought, str) or not thought.strip():
            raise ValueError("thought must be a non-empty string")
        return ThinkInput(thought=thought)

    def is_read_only(self, parsed_input: ThinkInput) -> bool:
        return True

    def is_concurrency_safe(self, parsed_input: ThinkInput) -> bool:
        return True

    async def call(self, parsed_input: ThinkInput, context: ToolContext) -> ToolResult:
        return ToolResult(content=parsed_input.thought.strip())
