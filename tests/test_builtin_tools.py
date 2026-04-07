from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_assist.tools.base import ToolContext
from unified_assist.tools.builtins.ask_user import AskUserTool
from unified_assist.tools.builtins.bash import BashTool
from unified_assist.tools.builtins.edit_file import EditFileTool
from unified_assist.tools.builtins.glob_search import GlobSearchTool
from unified_assist.tools.builtins.read_file import ReadFileTool
from unified_assist.tools.builtins.think import ThinkTool
from unified_assist.tools.builtins.write_file import WriteFileTool


class BuiltinToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_file_tools_and_glob(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = ToolContext(cwd=Path(tmp))
            write_tool = WriteFileTool()
            read_tool = ReadFileTool()
            edit_tool = EditFileTool()
            glob_tool = GlobSearchTool()

            await write_tool.call(write_tool.parse_input({"path": "a.txt", "content": "hello"}), context)
            read_result = await read_tool.call(read_tool.parse_input({"path": "a.txt"}), context)
            self.assertEqual(read_result.content, "hello")

            await edit_tool.call(
                edit_tool.parse_input({"path": "a.txt", "old": "hello", "new": "world"}),
                context,
            )
            edited = await read_tool.call(read_tool.parse_input({"path": "a.txt"}), context)
            self.assertEqual(edited.content, "world")

            glob_result = await glob_tool.call(glob_tool.parse_input({"pattern": "*.txt"}), context)
            self.assertEqual(glob_result.content, "a.txt")

    async def test_bash_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = ToolContext(cwd=Path(tmp))
            tool = BashTool()
            result = await tool.call(tool.parse_input({"command": "printf hello", "timeout": 5}), context)
            self.assertEqual(result.content, "hello")
            self.assertTrue(tool.is_read_only(tool.parse_input({"command": "printf hello"})))

    async def test_think_and_ask_user_tools(self) -> None:
        context = ToolContext(cwd=Path.cwd())
        think_result = await ThinkTool().call(ThinkTool().parse_input({"thought": "Focus"}), context)
        ask_result = await AskUserTool().call(
            AskUserTool().parse_input({"question": "Which file?"}), context
        )
        self.assertEqual(think_result.content, "Focus")
        self.assertTrue(ask_result.metadata["needs_user_input"])


if __name__ == "__main__":
    unittest.main()
