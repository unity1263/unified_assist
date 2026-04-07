from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_assist.tools.base import ToolContext
from unified_assist.tools.builtins.lsp import LSPTool
from unified_assist.tools.builtins.web_common import FetchedPage, SearchResult
from unified_assist.tools.builtins.web_fetch import WebFetchTool
from unified_assist.tools.builtins.web_search import WebSearchTool


class WebAndLspTests(unittest.IsolatedAsyncioTestCase):
    async def test_web_fetch_tool_reads_html(self) -> None:
        tool = WebFetchTool()
        context = ToolContext(
            cwd=Path.cwd(),
            metadata={
                "web_fetch_transport": lambda url, max_chars=12000: FetchedPage(
                    requested_url=url,
                    final_url=url,
                    status_code=200,
                    content_type="text/html; charset=utf-8",
                    title="Test Page",
                    content="Welcome\nAlpha section.\nBeta section.",
                )
            },
        )
        result = await tool.call(
            tool.parse_input(
                {
                    "url": "https://example.com/demo",
                    "prompt": "Summarize the visible sections",
                }
            ),
            context,
        )
        self.assertIn("Title: Test Page", result.content)
        self.assertIn("Alpha section.", result.content)
        self.assertIn("Requested extraction: Summarize the visible sections", result.content)

    async def test_web_search_tool_formats_and_filters_results(self) -> None:
        tool = WebSearchTool()
        context = ToolContext(
            cwd=Path.cwd(),
            metadata={
                "web_search_provider": lambda query, max_results: [
                    SearchResult(
                        title="Allowed result",
                        url="https://docs.example.com/page",
                        snippet="Primary documentation",
                    ),
                    SearchResult(
                        title="Blocked result",
                        url="https://ads.bad.example/page",
                        snippet="Should be filtered",
                    ),
                ]
            },
        )
        result = await tool.call(
            tool.parse_input(
                {
                    "query": "example docs",
                    "domains": ["example.com"],
                    "blocked_domains": ["bad.example"],
                }
            ),
            context,
        )
        self.assertIn("Allowed result", result.content)
        self.assertNotIn("Blocked result", result.content)
        self.assertEqual(result.metadata["results"][0]["url"], "https://docs.example.com/page")

    async def test_lsp_tool_supports_python_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            (cwd / "main.py").write_text(
                "\n".join(
                    [
                        "def helper():",
                        '    \"\"\"Helper docs.\"\"\"',
                        '    return \"ok\"',
                        "",
                        "def runner():",
                        "    return helper()",
                        "",
                    ]
                ),
                encoding="utf-8",
            )
            (cwd / "other.py").write_text(
                "\n".join(
                    [
                        "from main import helper",
                        "",
                        "def consumer():",
                        "    return helper()",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            tool = LSPTool()
            context = ToolContext(cwd=cwd)

            document_symbols = await tool.call(
                tool.parse_input({"operation": "documentSymbol", "file_path": "main.py"}),
                context,
            )
            self.assertIn("function helper", document_symbols.content)
            self.assertIn("function runner", document_symbols.content)

            hover = await tool.call(
                tool.parse_input(
                    {
                        "operation": "hover",
                        "file_path": "main.py",
                        "line": 6,
                        "character": 13,
                    }
                ),
                context,
            )
            self.assertIn("Documentation: Helper docs.", hover.content)

            definition = await tool.call(
                tool.parse_input(
                    {
                        "operation": "goToDefinition",
                        "file_path": "main.py",
                        "line": 6,
                        "character": 13,
                    }
                ),
                context,
            )
            self.assertIn("main.py:1:5", definition.content)

            references = await tool.call(
                tool.parse_input(
                    {
                        "operation": "findReferences",
                        "file_path": "main.py",
                        "line": 6,
                        "character": 13,
                    }
                ),
                context,
            )
            self.assertIn("main.py:6", references.content)
            self.assertIn("other.py:1", references.content)

            outgoing = await tool.call(
                tool.parse_input(
                    {
                        "operation": "outgoingCalls",
                        "file_path": "main.py",
                        "line": 6,
                        "character": 8,
                    }
                ),
                context,
            )
            self.assertIn("Outgoing calls from runner", outgoing.content)
            self.assertIn("helper -> main.py:1:5", outgoing.content)

            incoming = await tool.call(
                tool.parse_input(
                    {
                        "operation": "incomingCalls",
                        "file_path": "main.py",
                        "line": 1,
                        "character": 6,
                    }
                ),
                context,
            )
            self.assertIn("runner", incoming.content)
            self.assertIn("consumer", incoming.content)

            workspace_symbols = await tool.call(
                tool.parse_input({"operation": "workspaceSymbol", "query": "help"}),
                context,
            )
            self.assertIn("helper", workspace_symbols.content)


if __name__ == "__main__":
    unittest.main()
