from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from unified_assist.tools.base import BaseTool, ToolContext, ToolResult


VALID_TODO_STATUSES = {"pending", "in_progress", "completed"}


@dataclass(slots=True)
class TodoItem:
    content: str
    status: str
    priority: str | None = None

    def to_dict(self) -> dict[str, str]:
        payload = {
            "content": self.content,
            "status": self.status,
        }
        if self.priority:
            payload["priority"] = self.priority
        return payload


@dataclass(slots=True)
class TodoWriteInput:
    todos: list[TodoItem]


class TodoWriteTool(BaseTool[TodoWriteInput]):
    name = "TodoWrite"
    description = "Update the session todo list"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                            "status": {"type": "string"},
                            "priority": {"type": "string"},
                        },
                        "required": ["content", "status"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["todos"],
            "additionalProperties": False,
        }

    def parse_input(self, raw_input: Mapping[str, Any]) -> TodoWriteInput:
        raw_todos = raw_input.get("todos")
        if not isinstance(raw_todos, list):
            raise ValueError("todos must be a list")
        todos: list[TodoItem] = []
        for item in raw_todos:
            if not isinstance(item, dict):
                raise ValueError("each todo must be an object")
            content = item.get("content")
            status = item.get("status")
            priority = item.get("priority")
            if not isinstance(content, str) or not content.strip():
                raise ValueError("todo content must be a non-empty string")
            if not isinstance(status, str) or status not in VALID_TODO_STATUSES:
                raise ValueError("todo status must be pending, in_progress, or completed")
            if priority is not None and not isinstance(priority, str):
                raise ValueError("todo priority must be a string")
            todos.append(TodoItem(content=content.strip(), status=status, priority=priority))
        return TodoWriteInput(todos=todos)

    async def call(self, parsed_input: TodoWriteInput, context: ToolContext) -> ToolResult:
        previous = context.metadata.get("todos", [])
        if not isinstance(previous, list):
            previous = []
        stored = [todo.to_dict() for todo in parsed_input.todos]
        if stored and all(item["status"] == "completed" for item in stored):
            stored = []
        summary = ["Updated todo list:"]
        for item in stored:
            summary.append(f"- [{item['status']}] {item['content']}")
        if not stored:
            summary.append("- all tasks completed")
        return ToolResult(
            content="\n".join(summary),
            metadata={
                "old_todos": previous,
                "context_patch": {"todos": stored},
            },
        )
