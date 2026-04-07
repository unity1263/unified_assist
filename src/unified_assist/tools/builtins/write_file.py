from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from unified_assist.tools.base import BaseTool, ToolContext, ToolResult


@dataclass(slots=True)
class WriteFileInput:
    path: str
    content: str


class WriteFileTool(BaseTool[WriteFileInput]):
    name = "write_file"
    description = "Write a text file"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        }

    def parse_input(self, raw_input: Mapping[str, Any]) -> WriteFileInput:
        path = raw_input.get("path")
        content = raw_input.get("content")
        if not isinstance(path, str) or not path.strip():
            raise ValueError("path must be a non-empty string")
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        return WriteFileInput(path=path, content=content)

    async def call(self, parsed_input: WriteFileInput, context: ToolContext) -> ToolResult:
        path = self.resolve_path(context, parsed_input.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(parsed_input.content, encoding="utf-8")
        return ToolResult(content=f"wrote {parsed_input.path}")
