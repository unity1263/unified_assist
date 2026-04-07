from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from unified_assist.tools.base import BaseTool, ToolContext, ToolResult, ValidationResult


def _display_path(path: Path, cwd: Path) -> str:
    try:
        return str(path.relative_to(cwd))
    except ValueError:
        return str(path)


def _numbered_text(lines: list[str], *, start_line: int) -> str:
    return "\n".join(f"{index:>6}\t{line}" for index, line in enumerate(lines, start=start_line))


@dataclass(slots=True)
class ClaudeReadInput:
    file_path: str
    offset: int = 1
    limit: int = 2000


class ClaudeReadTool(BaseTool[ClaudeReadInput]):
    name = "Read"
    description = "Read a file from the local filesystem with line numbers"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "path": {"type": "string"},
                "offset": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1},
            },
            "required": [],
            "additionalProperties": False,
        }

    def parse_input(self, raw_input: Mapping[str, Any]) -> ClaudeReadInput:
        file_path = raw_input.get("file_path", raw_input.get("path"))
        if not isinstance(file_path, str) or not file_path.strip():
            raise ValueError("file_path must be a non-empty string")
        offset = raw_input.get("offset", 1)
        limit = raw_input.get("limit", 2000)
        if not isinstance(offset, int) or offset <= 0:
            raise ValueError("offset must be a positive integer")
        if not isinstance(limit, int) or limit <= 0:
            raise ValueError("limit must be a positive integer")
        return ClaudeReadInput(file_path=file_path, offset=offset, limit=limit)

    def is_read_only(self, parsed_input: ClaudeReadInput) -> bool:
        return True

    def is_concurrency_safe(self, parsed_input: ClaudeReadInput) -> bool:
        return True

    async def validate(self, parsed_input: ClaudeReadInput, context: ToolContext) -> ValidationResult:
        path = self.resolve_path(context, parsed_input.file_path)
        if not path.exists() or not path.is_file():
            return ValidationResult.failure(f"file not found: {parsed_input.file_path}")
        return ValidationResult.success()

    async def call(self, parsed_input: ClaudeReadInput, context: ToolContext) -> ToolResult:
        path = self.resolve_path(context, parsed_input.file_path)
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = parsed_input.offset - 1
        end = start + parsed_input.limit
        window = lines[start:end]
        if not window:
            return ToolResult(content="")
        return ToolResult(content=_numbered_text(window, start_line=parsed_input.offset))


@dataclass(slots=True)
class ClaudeWriteInput:
    file_path: str
    content: str


class ClaudeWriteTool(BaseTool[ClaudeWriteInput]):
    name = "Write"
    description = "Write a text file to the local filesystem"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["content"],
            "additionalProperties": False,
        }

    def parse_input(self, raw_input: Mapping[str, Any]) -> ClaudeWriteInput:
        file_path = raw_input.get("file_path", raw_input.get("path"))
        content = raw_input.get("content")
        if not isinstance(file_path, str) or not file_path.strip():
            raise ValueError("file_path must be a non-empty string")
        if not isinstance(content, str):
            raise ValueError("content must be a string")
        return ClaudeWriteInput(file_path=file_path, content=content)

    async def call(self, parsed_input: ClaudeWriteInput, context: ToolContext) -> ToolResult:
        path = self.resolve_path(context, parsed_input.file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(parsed_input.content, encoding="utf-8")
        return ToolResult(content=f"Wrote {_display_path(path, context.cwd)}")


@dataclass(slots=True)
class ClaudeEditInput:
    file_path: str
    old_string: str
    new_string: str
    replace_all: bool = False


class ClaudeEditTool(BaseTool[ClaudeEditInput]):
    name = "Edit"
    description = "Replace text in a file"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "path": {"type": "string"},
                "old_string": {"type": "string"},
                "old": {"type": "string"},
                "new_string": {"type": "string"},
                "new": {"type": "string"},
                "replace_all": {"type": "boolean"},
            },
            "required": [],
            "additionalProperties": False,
        }

    def parse_input(self, raw_input: Mapping[str, Any]) -> ClaudeEditInput:
        file_path = raw_input.get("file_path", raw_input.get("path"))
        old_string = raw_input.get("old_string", raw_input.get("old"))
        new_string = raw_input.get("new_string", raw_input.get("new"))
        replace_all = raw_input.get("replace_all", False)
        if not isinstance(file_path, str) or not file_path.strip():
            raise ValueError("file_path must be a non-empty string")
        if not isinstance(old_string, str) or not old_string:
            raise ValueError("old_string must be a non-empty string")
        if not isinstance(new_string, str):
            raise ValueError("new_string must be a string")
        if not isinstance(replace_all, bool):
            raise ValueError("replace_all must be a boolean")
        return ClaudeEditInput(
            file_path=file_path,
            old_string=old_string,
            new_string=new_string,
            replace_all=replace_all,
        )

    async def validate(self, parsed_input: ClaudeEditInput, context: ToolContext) -> ValidationResult:
        path = self.resolve_path(context, parsed_input.file_path)
        if not path.exists() or not path.is_file():
            return ValidationResult.failure(f"file not found: {parsed_input.file_path}")
        content = path.read_text(encoding="utf-8", errors="replace")
        if parsed_input.old_string not in content:
            return ValidationResult.failure("target text not found in file")
        return ValidationResult.success()

    async def call(self, parsed_input: ClaudeEditInput, context: ToolContext) -> ToolResult:
        path = self.resolve_path(context, parsed_input.file_path)
        content = path.read_text(encoding="utf-8", errors="replace")
        count = -1 if parsed_input.replace_all else 1
        updated = content.replace(parsed_input.old_string, parsed_input.new_string, count)
        path.write_text(updated, encoding="utf-8")
        return ToolResult(content=f"Edited {_display_path(path, context.cwd)}")


@dataclass(slots=True)
class ClaudeGlobInput:
    pattern: str
    path: str | None = None


class ClaudeGlobTool(BaseTool[ClaudeGlobInput]):
    name = "Glob"
    description = "Find files by glob pattern"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        }

    def parse_input(self, raw_input: Mapping[str, Any]) -> ClaudeGlobInput:
        pattern = raw_input.get("pattern")
        path = raw_input.get("path")
        if not isinstance(pattern, str) or not pattern.strip():
            raise ValueError("pattern must be a non-empty string")
        if path is not None and not isinstance(path, str):
            raise ValueError("path must be a string")
        return ClaudeGlobInput(pattern=pattern, path=path)

    def is_read_only(self, parsed_input: ClaudeGlobInput) -> bool:
        return True

    def is_concurrency_safe(self, parsed_input: ClaudeGlobInput) -> bool:
        return True

    async def validate(self, parsed_input: ClaudeGlobInput, context: ToolContext) -> ValidationResult:
        if not parsed_input.path:
            return ValidationResult.success()
        base = self.resolve_path(context, parsed_input.path)
        if not base.exists():
            return ValidationResult.failure(f"path not found: {parsed_input.path}")
        if not base.is_dir():
            return ValidationResult.failure(f"path is not a directory: {parsed_input.path}")
        return ValidationResult.success()

    async def call(self, parsed_input: ClaudeGlobInput, context: ToolContext) -> ToolResult:
        base = self.resolve_path(context, parsed_input.path) if parsed_input.path else context.cwd
        matches = sorted(
            _display_path(path, context.cwd)
            for path in base.glob(parsed_input.pattern)
            if path.is_file()
        )
        return ToolResult(content="\n".join(matches))
