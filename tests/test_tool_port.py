from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_assist.app.minimax_runner import build_builtin_tool_registry
from unified_assist.skills.bundled import load_bundled_skills
from unified_assist.tools.base import ToolContext
from unified_assist.tools.builtins.compat_fs import (
    ClaudeEditTool,
    ClaudeGlobTool,
    ClaudeReadTool,
    ClaudeWriteTool,
)
from unified_assist.tools.builtins.compat_interaction import ClaudeAgentTool, ClaudeAskUserQuestionTool
from unified_assist.tools.builtins.grep import GrepTool
from unified_assist.tools.builtins.skill_tool import SkillTool
from unified_assist.tools.builtins.todo_write import TodoWriteTool
from unified_assist.tools.builtins.tool_search import ToolSearchTool


class ClaudeCodePortTests(unittest.IsolatedAsyncioTestCase):
    async def test_builtin_registry_includes_claude_code_compat_tools(self) -> None:
        registry = build_builtin_tool_registry()
        names = set(registry.names())
        self.assertTrue(
            {
                "Read",
                "Write",
                "Edit",
                "Glob",
                "Grep",
                "Bash",
                "AskUserQuestion",
                "Skill",
                "ToolSearch",
                "TodoWrite",
                "Agent",
                "Task",
                "read_file",
                "spawn_agent",
            }.issubset(names)
        )

    async def test_claude_fs_tools_and_grep(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            context = ToolContext(cwd=cwd)
            writer = ClaudeWriteTool()
            await writer.call(
                writer.parse_input(
                    {
                        "file_path": "src/demo.txt",
                        "content": "alpha\nbeta\nalpha again\n",
                    }
                ),
                context,
            )
            reader = ClaudeReadTool()
            read_result = await reader.call(
                reader.parse_input({"file_path": "src/demo.txt", "offset": 2, "limit": 2}),
                context,
            )
            self.assertIn("2\tbeta", read_result.content)
            self.assertIn("3\talpha again", read_result.content)

            editor = ClaudeEditTool()
            await editor.call(
                editor.parse_input(
                    {
                        "file_path": "src/demo.txt",
                        "old_string": "beta",
                        "new_string": "gamma",
                    }
                ),
                context,
            )
            grep = GrepTool()
            grep_result = await grep.call(
                grep.parse_input(
                    {
                        "pattern": "alpha|gamma",
                        "path": "src",
                        "output_mode": "content",
                    }
                ),
                context,
            )
            self.assertIn("src/demo.txt:1:alpha", grep_result.content)
            self.assertIn("src/demo.txt:2:gamma", grep_result.content)

            glob = ClaudeGlobTool()
            glob_result = await glob.call(glob.parse_input({"pattern": "**/*.txt"}), context)
            self.assertIn("src/demo.txt", glob_result.content)

    async def test_skill_tool_lists_searches_and_invokes_skills(self) -> None:
        skills = load_bundled_skills()
        catalog = {skill.name: skill for skill in skills}
        context = ToolContext(
            cwd=Path.cwd(),
            metadata={
                "skill_catalog": catalog,
                "invoked_skills": [],
            },
        )
        tool = SkillTool()
        listed = await tool.call(tool.parse_input({"action": "list"}), context)
        self.assertIn("simplify:", listed.content)

        searched = await tool.call(tool.parse_input({"action": "search", "query": "verify"}), context)
        self.assertIn("verify:", searched.content)

        invoked = await tool.call(
            tool.parse_input({"skill": "simplify", "arguments": "focus on test quality"}),
            context,
        )
        self.assertIn("# Skill: simplify", invoked.content)
        self.assertIn("focus on test quality", invoked.content)
        self.assertEqual(invoked.metadata["context_patch"]["invoked_skills"], ["simplify"])

    async def test_tool_search_and_todo_write(self) -> None:
        registry = build_builtin_tool_registry()
        context = ToolContext(cwd=Path.cwd(), metadata={"tool_registry": registry, "todos": []})

        search = ToolSearchTool()
        result = await search.call(search.parse_input({"query": "search file contents"}), context)
        self.assertIn("Grep:", result.content)

        todo_tool = TodoWriteTool()
        todo_result = await todo_tool.call(
            todo_tool.parse_input(
                {
                    "todos": [
                        {"content": "inspect files", "status": "completed"},
                        {"content": "run tests", "status": "in_progress"},
                    ]
                }
            ),
            context,
        )
        self.assertIn("Updated todo list:", todo_result.content)
        self.assertEqual(len(todo_result.metadata["context_patch"]["todos"]), 2)

        cleared = await todo_tool.call(
            todo_tool.parse_input(
                {
                    "todos": [
                        {"content": "inspect files", "status": "completed"},
                        {"content": "run tests", "status": "completed"},
                    ]
                }
            ),
            context,
        )
        self.assertEqual(cleared.metadata["context_patch"]["todos"], [])

    async def test_structured_ask_user_and_agent_alias_parsing(self) -> None:
        ask_tool = ClaudeAskUserQuestionTool()
        ask_result = await ask_tool.call(
            ask_tool.parse_input(
                {
                    "question": "Which path should we take?",
                    "options": [
                        {"label": "Option A", "description": "Smaller change"},
                        {"label": "Option B", "description": "Broader refactor"},
                    ],
                }
            ),
            ToolContext(cwd=Path.cwd()),
        )
        self.assertTrue(ask_result.metadata["needs_user_input"])
        self.assertIn("Option A", ask_result.content)

        parsed = ClaudeAgentTool().parse_input(
            {
                "prompt": "Investigate tests",
                "subagent_type": "general-purpose",
            }
        )
        self.assertEqual(parsed.agent_type, "general-purpose")


if __name__ == "__main__":
    unittest.main()
