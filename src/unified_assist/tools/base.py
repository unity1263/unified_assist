from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, Mapping, TypeVar

from unified_assist.tools.permissions import PermissionDecision, PermissionMode, allow_decision


InputT = TypeVar("InputT")


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(slots=True)
class ValidationResult:
    ok: bool
    message: str = ""

    @classmethod
    def success(cls) -> "ValidationResult":
        return cls(ok=True)

    @classmethod
    def failure(cls, message: str) -> "ValidationResult":
        return cls(ok=False, message=message)


@dataclass(slots=True)
class ToolResult:
    content: str
    is_error: bool = False
    data: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ToolCall:
    name: str
    input: dict[str, Any]
    tool_use_id: str


@dataclass(slots=True)
class ToolContext:
    cwd: Path
    permission_mode: PermissionMode = PermissionMode.DEFAULT
    metadata: dict[str, Any] = field(default_factory=dict)

    def snapshot(
        self,
        *,
        cwd: Path | None = None,
        permission_mode: PermissionMode | None = None,
        metadata_updates: Mapping[str, Any] | None = None,
    ) -> "ToolContext":
        metadata = dict(self.metadata)
        if metadata_updates:
            metadata.update(metadata_updates)
        return ToolContext(
            cwd=Path(cwd or self.cwd),
            permission_mode=permission_mode or self.permission_mode,
            metadata=metadata,
        )

    def merge_metadata(self, updates: Mapping[str, Any]) -> None:
        self.metadata.update(dict(updates))


class BaseTool(ABC, Generic[InputT]):
    name: str
    description: str

    def is_enabled(self) -> bool:
        return True

    def is_read_only(self, parsed_input: InputT) -> bool:
        return False

    def is_concurrency_safe(self, parsed_input: InputT) -> bool:
        return False

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        }

    def tool_spec(self) -> ToolSpec:
        return ToolSpec(
            name=self.name,
            description=self.description,
            input_schema=self.input_schema(),
        )

    def describe_call(self, parsed_input: InputT) -> str:
        return self.description

    @abstractmethod
    def parse_input(self, raw_input: Mapping[str, Any]) -> InputT:
        raise NotImplementedError

    async def validate(self, parsed_input: InputT, context: ToolContext) -> ValidationResult:
        return ValidationResult.success()

    async def check_permission(
        self, parsed_input: InputT, context: ToolContext
    ) -> PermissionDecision:
        return allow_decision()

    @abstractmethod
    async def call(self, parsed_input: InputT, context: ToolContext) -> ToolResult:
        raise NotImplementedError

    def resolve_path(self, context: ToolContext, path: str) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return (context.cwd / candidate).resolve()
