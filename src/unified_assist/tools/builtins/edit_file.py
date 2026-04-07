from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from unified_assist.tools.base import BaseTool, ToolContext, ToolResult, ValidationResult


@dataclass(slots=True)
class EditFileInput:
    path: str
    old: str
    new: str


class EditFileTool(BaseTool[EditFileInput]):
    name = "edit_file"
    description = "Replace text in a file"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old": {"type": "string"},
                "new": {"type": "string"},
            },
            "required": ["path", "old", "new"],
            "additionalProperties": False,
        }

    def parse_input(self, raw_input: Mapping[str, Any]) -> EditFileInput:
        path = raw_input.get("path")
        old = raw_input.get("old")
        new = raw_input.get("new")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")
        if not isinstance(old, str) or not old:
            raise ValueError("old must be a non-empty string")
        if not isinstance(new, str):
            raise ValueError("new must be a string")
        return EditFileInput(path=path, old=old, new=new)

    async def validate(self, parsed_input: EditFileInput, context: ToolContext) -> ValidationResult:
        path = self.resolve_path(context, parsed_input.path)
        if not path.exists():
            return ValidationResult.failure(f"file not found: {parsed_input.path}")
        content = path.read_text(encoding="utf-8")
        if parsed_input.old not in content:
            return ValidationResult.failure("target text not found in file")
        return ValidationResult.success()

    async def call(self, parsed_input: EditFileInput, context: ToolContext) -> ToolResult:
        path = self.resolve_path(context, parsed_input.path)
        content = path.read_text(encoding="utf-8")
        updated = content.replace(parsed_input.old, parsed_input.new, 1)
        path.write_text(updated, encoding="utf-8")
        return ToolResult(content=f"edited {parsed_input.path}")
