from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from unified_assist.app.minimax_runner import (
    _main,
    build_argument_parser,
    build_builtin_tool_registry,
    build_minimax_session_engine,
)
from unified_assist.llm import MiniMaxAdapter


class MiniMaxRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_main_requires_api_key(self) -> None:
        original = os.environ.pop("MINIMAX_API_KEY", None)
        try:
            with self.assertRaisesRegex(RuntimeError, "MINIMAX_API_KEY is required"):
                await _main()
        finally:
            if original is not None:
                os.environ["MINIMAX_API_KEY"] = original

    async def test_build_minimax_session_engine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            engine = build_minimax_session_engine(
                cwd=Path(tmp),
                api_key="secret",
                base_url="https://api.minimaxi.com/v1",
            )
            self.assertIsInstance(engine.agent_loop.model, MiniMaxAdapter)
            self.assertEqual(engine.config.session_id, "minimax-smoke")
            self.assertIn("read_file", engine.agent_loop.tool_executor.registry.names())
            self.assertIn("spawn_agent", engine.agent_loop.tool_executor.registry.names())
            self.assertIn("Skill", engine.agent_loop.tool_executor.registry.names())
            self.assertIn("simplify", {skill.name for skill in engine.agent_loop.skills})

    async def test_build_builtin_tool_registry(self) -> None:
        registry = build_builtin_tool_registry()
        self.assertTrue(
            {
                "AskUserQuestion",
                "Bash",
                "Edit",
                "Glob",
                "Grep",
                "Read",
                "Skill",
                "Task",
                "TodoWrite",
                "ToolSearch",
                "Write",
                "ask_user",
                "spawn_agent",
            }.issubset(set(registry.names()))
        )

    async def test_argument_parser_defaults(self) -> None:
        parser = build_argument_parser()
        args = parser.parse_args([])
        self.assertEqual(args.model, "MiniMax-M2.7")
        self.assertEqual(args.base_url, "https://api.minimaxi.com/v1")


if __name__ == "__main__":
    unittest.main()
