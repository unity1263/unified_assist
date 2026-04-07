from __future__ import annotations

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from unified_assist.skills.hooks import SkillHookRegistry
from unified_assist.messages.models import ToolResultMessage
from unified_assist.tools.base import BaseTool, ToolCall, ToolContext, ToolResult
from unified_assist.tools.executor import ToolContextUpdate, ToolExecutor, ToolProgressUpdate, ToolResultUpdate
from unified_assist.tools.permissions import PermissionMode, ask_decision, decide_permission
from unified_assist.tools.registry import ToolRegistry
from unified_assist.tools.result_store import ToolResultStore


@dataclass(slots=True)
class DummyInput:
    value: str


class DummyTool(BaseTool[DummyInput]):
    name = "dummy"
    description = "dummy"

    def __init__(self, *, concurrency_safe: bool = True, read_only: bool = True) -> None:
        self._concurrency_safe = concurrency_safe
        self._read_only = read_only

    def parse_input(self, raw_input: Mapping[str, Any]) -> DummyInput:
        value = raw_input.get("value")
        if not isinstance(value, str):
            raise ValueError("bad input")
        return DummyInput(value)

    def is_concurrency_safe(self, parsed_input: DummyInput) -> bool:
        return self._concurrency_safe

    def is_read_only(self, parsed_input: DummyInput) -> bool:
        return self._read_only

    def describe_call(self, parsed_input: DummyInput) -> str:
        return f"dummy:{parsed_input.value}"

    async def call(self, parsed_input: DummyInput, context: ToolContext) -> ToolResult:
        return ToolResult(content=f"ok:{parsed_input.value}")


class ContextPatchTool(DummyTool):
    async def call(self, parsed_input: DummyInput, context: ToolContext) -> ToolResult:
        return ToolResult(
            content=f"patched:{parsed_input.value}",
            metadata={"context_patch": {"last_dummy_value": parsed_input.value}},
        )


class AskPermissionTool(DummyTool):
    def __init__(self) -> None:
        super().__init__(concurrency_safe=False, read_only=False)

    async def check_permission(self, parsed_input: DummyInput, context: ToolContext):
        return ask_decision("need approval")


class ToolFoundationTests(unittest.IsolatedAsyncioTestCase):
    async def test_permissions_and_registry(self) -> None:
        self.assertEqual(decide_permission(PermissionMode.READ_ONLY, is_read_only=False).behavior, "deny")
        registry = ToolRegistry()
        registry.register(DummyTool())
        self.assertEqual(registry.names(), ["dummy"])
        with self.assertRaises(ValueError):
            registry.register(DummyTool())

    async def test_result_store_persists_large_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = ToolResultStore(tmp, max_inline_chars=10)
            persisted = store.persist_if_needed("dummy", "id-1", ToolResult(content="0123456789abcdefghij"))
            self.assertIn("persisted to", persisted.content)
            self.assertTrue(Path(persisted.metadata["persisted_path"]).exists())

    async def test_executor_runs_tool_and_handles_invalid_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = ToolRegistry()
            registry.register(DummyTool())
            executor = ToolExecutor(registry, ToolResultStore(tmp))
            context = ToolContext(cwd=Path(tmp))
            results = await executor.execute_calls(
                [
                    ToolCall(name="dummy", input={"value": "x"}, tool_use_id="1"),
                    ToolCall(name="dummy", input={"value": 1}, tool_use_id="2"),
                ],
                context,
            )
            self.assertEqual(len(results), 2)
            self.assertIsInstance(results[0], ToolResultMessage)
            self.assertFalse(results[0].results[0].is_error)
            self.assertTrue(results[1].results[0].is_error)

    async def test_execute_stream_emits_progress_hooks_and_context_updates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = ToolRegistry()
            registry.register(ContextPatchTool())
            executor = ToolExecutor(registry, ToolResultStore(tmp))
            hook_registry = SkillHookRegistry()
            hook_registry.register(
                "pre_tool",
                "planning",
                lambda payload: {"message": "pre hook fired", "metadata_updates": {"hook_seen": True}},
            )
            hook_registry.register(
                "post_tool",
                "planning",
                lambda payload: "post hook fired",
            )
            context = ToolContext(cwd=Path(tmp))
            updates = [
                update
                async for update in executor.execute_stream(
                    [ToolCall(name="dummy", input={"value": "x"}, tool_use_id="1")],
                    context,
                    hook_registry=hook_registry,
                )
            ]
            self.assertIsInstance(updates[0], ToolProgressUpdate)
            self.assertEqual(updates[0].stage, "tool_started")
            self.assertIsInstance(updates[1], ToolProgressUpdate)
            self.assertEqual(updates[1].message, "pre hook fired")
            self.assertIsInstance(updates[2], ToolContextUpdate)
            self.assertEqual(updates[2].metadata["hook_seen"], True)
            self.assertIsInstance(updates[3], ToolContextUpdate)
            self.assertEqual(updates[3].metadata["last_dummy_value"], "x")
            self.assertIsInstance(updates[4], ToolProgressUpdate)
            self.assertEqual(updates[4].message, "post hook fired")
            self.assertIsInstance(updates[5], ToolResultUpdate)
            self.assertEqual(updates[5].message.results[0].content, "patched:x")

    async def test_execute_stream_bubbles_permission_request(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry = ToolRegistry()
            registry.register(AskPermissionTool())
            executor = ToolExecutor(registry, ToolResultStore(tmp))
            context = ToolContext(cwd=Path(tmp), permission_mode=PermissionMode.ACCEPT_EDITS)
            updates = [
                update
                async for update in executor.execute_stream(
                    [ToolCall(name="dummy", input={"value": "x"}, tool_use_id="1")],
                    context,
                )
            ]
            self.assertIsInstance(updates[-1], ToolResultUpdate)
            self.assertTrue(updates[-1].message.metadata["needs_permission"])
            self.assertEqual(updates[-1].message.metadata["permission_behavior"], "ask")


if __name__ == "__main__":
    unittest.main()
