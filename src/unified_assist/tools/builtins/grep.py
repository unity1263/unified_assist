from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from unified_assist.tools.base import BaseTool, ToolContext, ToolResult, ValidationResult


def _display_path(path: Path, cwd: Path) -> str:
    try:
        return str(path.relative_to(cwd))
    except ValueError:
        return str(path)


def _iter_files(base: Path) -> Iterable[Path]:
    if base.is_file():
        yield base
        return
    for path in sorted(base.rglob("*")):
        if path.is_file():
            yield path


@dataclass(slots=True)
class GrepInput:
    pattern: str
    path: str | None = None
    glob: str | None = None
    output_mode: str = "files_with_matches"
    ignore_case: bool = False
    head_limit: int = 50
    offset: int = 0
    multiline: bool = False
    file_type: str | None = None
    show_line_numbers: bool = True


class GrepTool(BaseTool[GrepInput]):
    name = "Grep"
    description = "Search file contents with a ripgrep-like interface"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "pattern": {"type": "string"},
                "path": {"type": "string"},
                "glob": {"type": "string"},
                "output_mode": {
                    "type": "string",
                    "enum": ["content", "files_with_matches", "count"],
                },
                "-i": {"type": "boolean"},
                "head_limit": {"type": "integer", "minimum": 0},
                "offset": {"type": "integer", "minimum": 0},
                "multiline": {"type": "boolean"},
                "type": {"type": "string"},
                "-n": {"type": "boolean"},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        }

    def parse_input(self, raw_input: Mapping[str, Any]) -> GrepInput:
        pattern = raw_input.get("pattern")
        if not isinstance(pattern, str) or not pattern.strip():
            raise ValueError("pattern must be a non-empty string")
        path = raw_input.get("path")
        glob = raw_input.get("glob")
        output_mode = raw_input.get("output_mode", "files_with_matches")
        head_limit = raw_input.get("head_limit", 50)
        offset = raw_input.get("offset", 0)
        multiline = raw_input.get("multiline", False)
        file_type = raw_input.get("type")
        if path is not None and not isinstance(path, str):
            raise ValueError("path must be a string")
        if glob is not None and not isinstance(glob, str):
            raise ValueError("glob must be a string")
        if output_mode not in {"content", "files_with_matches", "count"}:
            raise ValueError("output_mode must be content, files_with_matches, or count")
        if not isinstance(head_limit, int) or head_limit < 0:
            raise ValueError("head_limit must be a non-negative integer")
        if not isinstance(offset, int) or offset < 0:
            raise ValueError("offset must be a non-negative integer")
        if not isinstance(multiline, bool):
            raise ValueError("multiline must be a boolean")
        if file_type is not None and not isinstance(file_type, str):
            raise ValueError("type must be a string")
        return GrepInput(
            pattern=pattern,
            path=path,
            glob=glob,
            output_mode=output_mode,
            ignore_case=bool(raw_input.get("-i", False)),
            head_limit=head_limit,
            offset=offset,
            multiline=multiline,
            file_type=file_type,
            show_line_numbers=bool(raw_input.get("-n", True)),
        )

    def is_read_only(self, parsed_input: GrepInput) -> bool:
        return True

    def is_concurrency_safe(self, parsed_input: GrepInput) -> bool:
        return True

    async def validate(self, parsed_input: GrepInput, context: ToolContext) -> ValidationResult:
        if parsed_input.path:
            path = self.resolve_path(context, parsed_input.path)
            if not path.exists():
                return ValidationResult.failure(f"path not found: {parsed_input.path}")
        try:
            re.compile(parsed_input.pattern, self._regex_flags(parsed_input))
        except re.error as exc:
            return ValidationResult.failure(f"invalid regex: {exc}")
        return ValidationResult.success()

    async def call(self, parsed_input: GrepInput, context: ToolContext) -> ToolResult:
        base = self.resolve_path(context, parsed_input.path) if parsed_input.path else context.cwd
        regex = re.compile(parsed_input.pattern, self._regex_flags(parsed_input))
        file_hits: list[str] = []
        content_hits: list[str] = []
        count_hits: list[str] = []

        for path in _iter_files(base):
            if not self._matches_filters(path, base, parsed_input):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            display_path = _display_path(path, context.cwd)
            if parsed_input.multiline:
                matches = list(regex.finditer(text))
                if not matches:
                    continue
                file_hits.append(display_path)
                if parsed_input.output_mode == "content":
                    for match in matches:
                        snippet = match.group(0).strip().splitlines()[0] if match.group(0).strip() else ""
                        content_hits.append(f"{display_path}:{snippet}")
                elif parsed_input.output_mode == "count":
                    count_hits.append(f"{display_path}:{len(matches)}")
                continue

            per_file_matches = 0
            for line_number, line in enumerate(text.splitlines(), start=1):
                if not regex.search(line):
                    continue
                per_file_matches += 1
                if parsed_input.output_mode == "content":
                    prefix = f"{display_path}:{line_number}:" if parsed_input.show_line_numbers else f"{display_path}:"
                    content_hits.append(f"{prefix}{line}")
            if per_file_matches:
                file_hits.append(display_path)
                if parsed_input.output_mode == "count":
                    count_hits.append(f"{display_path}:{per_file_matches}")

        if parsed_input.output_mode == "content":
            output = self._slice(content_hits, parsed_input)
        elif parsed_input.output_mode == "count":
            output = self._slice(count_hits, parsed_input)
        else:
            output = self._slice(sorted(set(file_hits)), parsed_input)
        return ToolResult(content="\n".join(output))

    def _regex_flags(self, parsed_input: GrepInput) -> int:
        flags = re.MULTILINE
        if parsed_input.ignore_case:
            flags |= re.IGNORECASE
        if parsed_input.multiline:
            flags |= re.DOTALL
        return flags

    def _matches_filters(self, path: Path, base: Path, parsed_input: GrepInput) -> bool:
        relative = str(path.relative_to(base)) if base.is_dir() else path.name
        if parsed_input.glob and not fnmatch.fnmatch(relative, parsed_input.glob):
            return False
        if parsed_input.file_type and path.suffix != f".{parsed_input.file_type.lstrip('.')}":
            return False
        return True

    def _slice(self, items: list[str], parsed_input: GrepInput) -> list[str]:
        start = parsed_input.offset
        if parsed_input.head_limit == 0:
            return items[start:]
        return items[start : start + parsed_input.head_limit]
