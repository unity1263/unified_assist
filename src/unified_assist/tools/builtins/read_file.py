from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from unified_assist.tools.base import BaseTool, ToolContext, ToolResult, ValidationResult


@dataclass(slots=True)
class ReadFileInput:
    path: str


class ReadFileTool(BaseTool[ReadFileInput]):
    name = "read_file"
    description = "Read a text file from the workspace"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Relative or absolute file path"}
            },
            "required": ["path"],
            "additionalProperties": False,
        }

    def parse_input(self, raw_input: Mapping[str, Any]) -> ReadFileInput:
        path = raw_input.get("path")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")
        return ReadFileInput(path=path)

    def is_read_only(self, parsed_input: ReadFileInput) -> bool:
        return True

    def is_concurrency_safe(self, parsed_input: ReadFileInput) -> bool:
        return True

    async def validate(self, parsed_input: ReadFileInput, context: ToolContext) -> ValidationResult:
        path = self.resolve_path(context, parsed_input.path)
        if not path.exists() or not path.is_file():
            return ValidationResult.failure(f"file not found: {parsed_input.path}")
        return ValidationResult.success()

    async def call(self, parsed_input: ReadFileInput, context: ToolContext) -> ToolResult:
        path = self.resolve_path(context, parsed_input.path)
        return ToolResult(content=path.read_text(encoding="utf-8"))
