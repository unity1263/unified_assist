from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypeAlias


@dataclass(frozen=True, slots=True)
class TextBlock:
    text: str
    type: str = field(init=False, default="text")

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "text": self.text}


@dataclass(frozen=True, slots=True)
class ThinkingBlock:
    text: str
    type: str = field(init=False, default="thinking")

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "text": self.text}


@dataclass(frozen=True, slots=True)
class ToolUseBlock:
    name: str
    input: dict[str, Any]
    tool_use_id: str
    type: str = field(init=False, default="tool_use")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "name": self.name,
            "input": self.input,
            "tool_use_id": self.tool_use_id,
        }


@dataclass(frozen=True, slots=True)
class ToolResultBlock:
    tool_use_id: str
    content: str
    is_error: bool = False
    type: str = field(init=False, default="tool_result")

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "tool_use_id": self.tool_use_id,
            "content": self.content,
            "is_error": self.is_error,
        }


AssistantBlock: TypeAlias = TextBlock | ThinkingBlock | ToolUseBlock
UserBlock: TypeAlias = ToolResultBlock
Block: TypeAlias = AssistantBlock | UserBlock


def block_from_dict(data: dict[str, Any]) -> Block:
    block_type = data["type"]
    if block_type == "text":
        return TextBlock(text=str(data["text"]))
    if block_type == "thinking":
        return ThinkingBlock(text=str(data["text"]))
    if block_type == "tool_use":
        return ToolUseBlock(
            name=str(data["name"]),
            input=dict(data.get("input", {})),
            tool_use_id=str(data["tool_use_id"]),
        )
    if block_type == "tool_result":
        return ToolResultBlock(
            tool_use_id=str(data["tool_use_id"]),
            content=str(data["content"]),
            is_error=bool(data.get("is_error", False)),
        )
    raise ValueError(f"unsupported block type: {block_type}")
