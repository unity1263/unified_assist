"""Built-in tools for Unified Claw."""

from unified_assist.tools.base import BaseTool
from unified_assist.tools.builtins.agent import AgentTool
from unified_assist.tools.builtins.ask_user import AskUserTool
from unified_assist.tools.builtins.bash import BashTool
from unified_assist.tools.builtins.compat_fs import (
    ClaudeEditTool,
    ClaudeGlobTool,
    ClaudeReadTool,
    ClaudeWriteTool,
)
from unified_assist.tools.builtins.compat_interaction import (
    ClaudeAgentTool,
    ClaudeAskUserQuestionTool,
    ClaudeBashTool,
    ClaudeTaskTool,
)
from unified_assist.tools.builtins.edit_file import EditFileTool
from unified_assist.tools.builtins.glob_search import GlobSearchTool
from unified_assist.tools.builtins.grep import GrepTool
from unified_assist.tools.builtins.lsp import LSPTool
from unified_assist.tools.builtins.read_file import ReadFileTool
from unified_assist.tools.builtins.skill_tool import SkillTool
from unified_assist.tools.builtins.think import ThinkTool
from unified_assist.tools.builtins.todo_write import TodoWriteTool
from unified_assist.tools.builtins.tool_search import ToolSearchTool
from unified_assist.tools.builtins.web_fetch import WebFetchTool
from unified_assist.tools.builtins.web_search import WebSearchTool
from unified_assist.tools.builtins.write_file import WriteFileTool


def builtin_tools(*, include_agent_tool: bool = True) -> list[BaseTool]:
    tools: list[BaseTool] = [
        ReadFileTool(),
        WriteFileTool(),
        EditFileTool(),
        GlobSearchTool(),
        BashTool(),
        ThinkTool(),
        AskUserTool(),
        ClaudeReadTool(),
        ClaudeWriteTool(),
        ClaudeEditTool(),
        ClaudeGlobTool(),
        GrepTool(),
        ClaudeBashTool(),
        ClaudeAskUserQuestionTool(),
        SkillTool(),
        ToolSearchTool(),
        TodoWriteTool(),
        WebFetchTool(),
        WebSearchTool(),
        LSPTool(),
    ]
    if include_agent_tool:
        tools.append(AgentTool())
        tools.append(ClaudeAgentTool())
        tools.append(ClaudeTaskTool())
    return tools


__all__ = [
    "AgentTool",
    "AskUserTool",
    "BashTool",
    "ClaudeAgentTool",
    "ClaudeAskUserQuestionTool",
    "ClaudeBashTool",
    "ClaudeEditTool",
    "ClaudeGlobTool",
    "ClaudeReadTool",
    "ClaudeTaskTool",
    "ClaudeWriteTool",
    "EditFileTool",
    "GrepTool",
    "LSPTool",
    "GlobSearchTool",
    "ReadFileTool",
    "SkillTool",
    "ThinkTool",
    "TodoWriteTool",
    "ToolSearchTool",
    "WebFetchTool",
    "WebSearchTool",
    "WriteFileTool",
    "builtin_tools",
]
