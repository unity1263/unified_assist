from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from unified_assist.tools.base import BaseTool, ToolContext, ToolResult
from unified_assist.tools.builtins.agent import AgentTool as SpawnAgentTool
from unified_assist.tools.builtins.bash import BashTool


@dataclass(slots=True)
class ClaudeAskUserQuestionInput:
    question: str
    options: list[dict[str, str]]
    multi_select: bool = False


class ClaudeAskUserQuestionTool(BaseTool[ClaudeAskUserQuestionInput]):
    name = "AskUserQuestion"
    description = "Pause and ask the user a structured clarifying question"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "options": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "description": {"type": "string"},
                        },
                        "required": ["label"],
                        "additionalProperties": False,
                    },
                },
                "multiSelect": {"type": "boolean"},
                "multi_select": {"type": "boolean"},
            },
            "required": ["question"],
            "additionalProperties": False,
        }

    def parse_input(self, raw_input: Mapping[str, Any]) -> ClaudeAskUserQuestionInput:
        question = raw_input.get("question")
        raw_options = raw_input.get("options", [])
        multi_select = raw_input.get("multi_select", raw_input.get("multiSelect", False))
        if not isinstance(question, str) or not question.strip():
            raise ValueError("question must be a non-empty string")
        if not isinstance(raw_options, list):
            raise ValueError("options must be a list")
        if not isinstance(multi_select, bool):
            raise ValueError("multi_select must be a boolean")
        options: list[dict[str, str]] = []
        for option in raw_options:
            if not isinstance(option, dict):
                raise ValueError("each option must be an object")
            label = option.get("label")
            description = option.get("description", "")
            if not isinstance(label, str) or not label.strip():
                raise ValueError("option label must be a non-empty string")
            if not isinstance(description, str):
                raise ValueError("option description must be a string")
            options.append({"label": label.strip(), "description": description.strip()})
        return ClaudeAskUserQuestionInput(
            question=question.strip(),
            options=options,
            multi_select=multi_select,
        )

    def is_read_only(self, parsed_input: ClaudeAskUserQuestionInput) -> bool:
        return True

    async def call(self, parsed_input: ClaudeAskUserQuestionInput, context: ToolContext) -> ToolResult:
        lines = [parsed_input.question]
        for index, option in enumerate(parsed_input.options, start=1):
            detail = f" - {option['description']}" if option["description"] else ""
            lines.append(f"{index}. {option['label']}{detail}")
        if parsed_input.multi_select:
            lines.append("User may select multiple options.")
        return ToolResult(
            content="USER_INPUT_REQUIRED: " + "\n".join(lines),
            metadata={"needs_user_input": True},
        )


class ClaudeBashTool(BashTool):
    name = "Bash"
    description = "Run a shell command in the current working directory"


class ClaudeAgentTool(SpawnAgentTool):
    name = "Agent"
    description = "Delegate bounded work to a child agent runtime"

    def input_schema(self) -> dict[str, Any]:
        schema = super().input_schema()
        properties = dict(schema.get("properties", {}))
        properties.update(
            {
                "subagent_type": {"type": "string"},
                "fork_context": {"type": "boolean"},
                "run_in_background": {"type": "boolean"},
                "isolation": {"type": "string"},
            }
        )
        schema["properties"] = properties
        return schema

    def parse_input(self, raw_input: Mapping[str, Any]):
        normalized = dict(raw_input)
        if "subagent_type" in normalized and "agent_type" not in normalized:
            normalized["agent_type"] = normalized["subagent_type"]
        if "fork_context" in normalized and "include_parent_context" not in normalized:
            normalized["include_parent_context"] = normalized["fork_context"]
        normalized.setdefault("description", "Delegate subtask")
        return super().parse_input(normalized)


class ClaudeTaskTool(ClaudeAgentTool):
    name = "Task"
    description = "Legacy alias for Agent"
