from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Mapping

from unified_assist.tools.base import BaseTool, ToolContext, ToolResult, ValidationResult


@dataclass(slots=True)
class BashInput:
    command: str
    timeout: int = 30


class BashTool(BaseTool[BashInput]):
    name = "bash"
    description = "Run a shell command"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "timeout": {"type": "integer", "minimum": 1},
            },
            "required": ["command"],
            "additionalProperties": False,
        }

    def parse_input(self, raw_input: Mapping[str, Any]) -> BashInput:
        command = raw_input.get("command")
        timeout = raw_input.get("timeout", 30)
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command must be a non-empty string")
        if not isinstance(timeout, int) or timeout <= 0:
            raise ValueError("timeout must be a positive integer")
        return BashInput(command=command, timeout=timeout)

    def is_read_only(self, parsed_input: BashInput) -> bool:
        banned_tokens = [">", ">>", "rm ", "mv ", "cp ", "touch ", "chmod ", "chown "]
        return not any(token in parsed_input.command for token in banned_tokens)

    def is_concurrency_safe(self, parsed_input: BashInput) -> bool:
        return self.is_read_only(parsed_input)

    async def validate(self, parsed_input: BashInput, context: ToolContext) -> ValidationResult:
        if "\x00" in parsed_input.command:
            return ValidationResult.failure("command contains null byte")
        return ValidationResult.success()

    async def call(self, parsed_input: BashInput, context: ToolContext) -> ToolResult:
        process = await asyncio.create_subprocess_shell(
            parsed_input.command,
            cwd=str(context.cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=parsed_input.timeout)
        except TimeoutError:
            process.kill()
            await process.communicate()
            return ToolResult(content="command timed out", is_error=True)

        output = stdout.decode("utf-8", errors="replace")
        error = stderr.decode("utf-8", errors="replace")
        content = output if not error else f"{output}\n{error}".strip()
        return ToolResult(content=content.strip(), is_error=process.returncode != 0)
