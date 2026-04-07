from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TypeAlias

from unified_assist.messages.blocks import (
    AssistantBlock,
    ToolResultBlock,
    ToolUseBlock,
    block_from_dict,
)


@dataclass(slots=True)
class SystemMessage:
    content: str
    type: str = field(init=False, default="system")


@dataclass(slots=True)
class UserMessage:
    content: str
    is_meta: bool = False
    type: str = field(init=False, default="user")


@dataclass(slots=True)
class AssistantMessage:
    blocks: list[AssistantBlock]
    stop_reason: str | None = None
    is_error: bool = False
    type: str = field(init=False, default="assistant")

    @property
    def text(self) -> str:
        return "\n".join(block.text for block in self.blocks if hasattr(block, "text")).strip()

    @property
    def tool_uses(self) -> list[ToolUseBlock]:
        return [block for block in self.blocks if isinstance(block, ToolUseBlock)]


@dataclass(slots=True)
class ToolResultMessage:
    results: list[ToolResultBlock]
    source_tool: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    type: str = field(init=False, default="tool_result")


@dataclass(slots=True)
class AttachmentMessage:
    kind: str
    data: dict[str, Any]
    type: str = field(init=False, default="attachment")


@dataclass(slots=True)
class ProgressMessage:
    content: str
    stage: str | None = None
    type: str = field(init=False, default="progress")


Message: TypeAlias = (
    SystemMessage
    | UserMessage
    | AssistantMessage
    | ToolResultMessage
    | AttachmentMessage
    | ProgressMessage
)


def message_to_dict(message: Message) -> dict[str, Any]:
    if isinstance(message, SystemMessage):
        return {"type": message.type, "content": message.content}
    if isinstance(message, UserMessage):
        return {"type": message.type, "content": message.content, "is_meta": message.is_meta}
    if isinstance(message, AssistantMessage):
        return {
            "type": message.type,
            "blocks": [block.to_dict() for block in message.blocks],
            "stop_reason": message.stop_reason,
            "is_error": message.is_error,
        }
    if isinstance(message, ToolResultMessage):
        return {
            "type": message.type,
            "results": [result.to_dict() for result in message.results],
            "source_tool": message.source_tool,
            "metadata": message.metadata,
        }
    if isinstance(message, AttachmentMessage):
        return {"type": message.type, "kind": message.kind, "data": message.data}
    if isinstance(message, ProgressMessage):
        return {"type": message.type, "content": message.content, "stage": message.stage}
    raise TypeError(f"unsupported message type: {type(message)!r}")


def message_from_dict(payload: dict[str, Any]) -> Message:
    message_type = payload["type"]
    if message_type == "system":
        return SystemMessage(content=str(payload["content"]))
    if message_type == "user":
        return UserMessage(
            content=str(payload["content"]),
            is_meta=bool(payload.get("is_meta", False)),
        )
    if message_type == "assistant":
        return AssistantMessage(
            blocks=[block_from_dict(item) for item in payload.get("blocks", [])],
            stop_reason=payload.get("stop_reason"),
            is_error=bool(payload.get("is_error", False)),
        )
    if message_type == "tool_result":
        return ToolResultMessage(
            results=[block_from_dict(item) for item in payload.get("results", [])],
            source_tool=payload.get("source_tool"),
            metadata=dict(payload.get("metadata", {})),
        )
    if message_type == "attachment":
        return AttachmentMessage(kind=str(payload["kind"]), data=dict(payload.get("data", {})))
    if message_type == "progress":
        return ProgressMessage(content=str(payload["content"]), stage=payload.get("stage"))
    raise ValueError(f"unsupported message type: {message_type}")
