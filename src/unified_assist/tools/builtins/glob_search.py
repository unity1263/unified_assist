from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from unified_assist.tools.base import BaseTool, ToolContext, ToolResult


@dataclass(slots=True)
class GlobSearchInput:
    pattern: str


class GlobSearchTool(BaseTool[GlobSearchInput]):
    name = "glob_search"
    description = "Find files by glob pattern"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        }

    def parse_input(self, raw_input: Mapping[str, Any]) -> GlobSearchInput:
        pattern = raw_input.get("pattern")
        if not isinstance(pattern, str) or not pattern.strip():
            raise ValueError("pattern must be a non-empty string")
        return GlobSearchInput(pattern=pattern)

    def is_read_only(self, parsed_input: GlobSearchInput) -> bool:
        return True

    def is_concurrency_safe(self, parsed_input: GlobSearchInput) -> bool:
        return True

    async def call(self, parsed_input: GlobSearchInput, context: ToolContext) -> ToolResult:
        matches = sorted(
            str(path.relative_to(context.cwd))
            for path in context.cwd.glob(parsed_input.pattern)
            if path.is_file()
        )
        return ToolResult(content="\n".join(matches))
