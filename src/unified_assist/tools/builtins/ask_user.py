from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from unified_assist.tools.base import BaseTool, ToolContext, ToolResult


@dataclass(slots=True)
class AskUserInput:
    question: str


class AskUserTool(BaseTool[AskUserInput]):
    name = "ask_user"
    description = "Pause and ask the user for clarification"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
            },
            "required": ["question"],
            "additionalProperties": False,
        }

    def parse_input(self, raw_input: Mapping[str, Any]) -> AskUserInput:
        question = raw_input.get("question")
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must be a non-empty string")
        return AskUserInput(question=question)

    def is_read_only(self, parsed_input: AskUserInput) -> bool:
        return True

    async def call(self, parsed_input: AskUserInput, context: ToolContext) -> ToolResult:
        return ToolResult(
            content=f"USER_INPUT_REQUIRED: {parsed_input.question.strip()}",
            metadata={"needs_user_input": True},
        )
