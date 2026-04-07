from __future__ import annotations

from dataclasses import dataclass, field

from unified_assist.tools.base import BaseTool, ToolSpec


@dataclass(slots=True)
class ToolRegistry:
    _tools: dict[str, BaseTool] = field(default_factory=dict)

    def register(self, tool: BaseTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(name for name, tool in self._tools.items() if tool.is_enabled())

    def visible_tools(self) -> list[BaseTool]:
        return [self._tools[name] for name in self.names()]

    def tool_specs(self) -> list[ToolSpec]:
        return [tool.tool_spec() for tool in self.visible_tools()]

    def subset(self, allowed_names: list[str] | None) -> "ToolRegistry":
        if allowed_names is None:
            clone = ToolRegistry()
            for tool in self.visible_tools():
                clone.register(tool)
            return clone

        allowed = set(allowed_names)
        clone = ToolRegistry()
        for name in self.names():
            if name in allowed:
                clone.register(self._tools[name])
        return clone
