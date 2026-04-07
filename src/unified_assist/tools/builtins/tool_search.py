from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping

from unified_assist.runtime.services import RuntimeServices
from unified_assist.tools.base import BaseTool, ToolContext, ToolResult
from unified_assist.tools.registry import ToolRegistry


def _tokenize(text: str) -> list[str]:
    return [token for token in re.split(r"[^a-z0-9]+", text.lower()) if token]


@dataclass(slots=True)
class ToolSearchInput:
    query: str
    max_results: int = 5


class ToolSearchTool(BaseTool[ToolSearchInput]):
    name = "ToolSearch"
    description = "Search the available tools by name or purpose"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1},
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    def parse_input(self, raw_input: Mapping[str, Any]) -> ToolSearchInput:
        query = raw_input.get("query")
        max_results = raw_input.get("max_results", 5)
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if not isinstance(max_results, int) or max_results <= 0:
            raise ValueError("max_results must be a positive integer")
        return ToolSearchInput(query=query.strip(), max_results=max_results)

    def is_read_only(self, parsed_input: ToolSearchInput) -> bool:
        return True

    def is_concurrency_safe(self, parsed_input: ToolSearchInput) -> bool:
        return True

    async def call(self, parsed_input: ToolSearchInput, context: ToolContext) -> ToolResult:
        registry = self._registry(context)
        if registry is None:
            return ToolResult(content="tool registry unavailable", is_error=True)

        query = parsed_input.query.lower()
        query_tokens = set(_tokenize(parsed_input.query))
        ranked: list[tuple[int, str]] = []
        for tool in registry.visible_tools():
            haystack = f"{tool.name} {tool.description}".lower()
            name_tokens = set(_tokenize(tool.name))
            desc_tokens = set(_tokenize(tool.description))
            score = 100
            if tool.name.lower() == query:
                score = 0
            elif query in tool.name.lower():
                score = 1
            elif query in haystack:
                score = 2
            else:
                overlap = len(query_tokens & (name_tokens | desc_tokens))
                if overlap:
                    score = 10 - min(overlap, 9)
            if score < 100:
                ranked.append((score, f"{tool.name}: {tool.description}"))
        ranked.sort(key=lambda item: (item[0], item[1].lower()))
        return ToolResult(content="\n".join(line for _, line in ranked[: parsed_input.max_results]))

    def _registry(self, context: ToolContext) -> ToolRegistry | None:
        registry = context.metadata.get("tool_registry")
        if isinstance(registry, ToolRegistry):
            return registry
        services = context.metadata.get("runtime_services")
        if isinstance(services, RuntimeServices):
            return services.tool_executor.registry
        return None
