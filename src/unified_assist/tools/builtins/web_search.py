from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from html import unescape
from typing import Any, Awaitable, Callable, Mapping, Sequence
from urllib import parse as urllib_parse

from unified_assist.tools.base import BaseTool, ToolContext, ToolResult, ValidationResult
from unified_assist.tools.builtins.web_common import SearchResult, fetch_raw_text, strip_html_fragment


WebSearchProvider = Callable[..., Sequence[SearchResult] | Awaitable[Sequence[SearchResult]]]

DEFAULT_WEB_SEARCH_URL = "https://duckduckgo.com/html/"


@dataclass(slots=True)
class WebSearchInput:
    query: str
    max_results: int = 5
    domains: list[str] | None = None
    blocked_domains: list[str] | None = None


class WebSearchTool(BaseTool[WebSearchInput]):
    name = "WebSearch"
    description = "Search the web and return structured search results with titles, snippets, and URLs"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 20},
                "domains": {"type": "array", "items": {"type": "string"}},
                "allowed_domains": {"type": "array", "items": {"type": "string"}},
                "blocked_domains": {"type": "array", "items": {"type": "string"}},
                "exclude_domains": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["query"],
            "additionalProperties": False,
        }

    def parse_input(self, raw_input: Mapping[str, Any]) -> WebSearchInput:
        query = raw_input.get("query")
        max_results = raw_input.get("max_results", 5)
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if not isinstance(max_results, int) or not (1 <= max_results <= 20):
            raise ValueError("max_results must be between 1 and 20")
        domains = self._parse_domains(raw_input.get("domains", raw_input.get("allowed_domains")))
        blocked_domains = self._parse_domains(
            raw_input.get("blocked_domains", raw_input.get("exclude_domains"))
        )
        return WebSearchInput(
            query=query.strip(),
            max_results=max_results,
            domains=domains,
            blocked_domains=blocked_domains,
        )

    def is_read_only(self, parsed_input: WebSearchInput) -> bool:
        return True

    def is_concurrency_safe(self, parsed_input: WebSearchInput) -> bool:
        return True

    async def validate(self, parsed_input: WebSearchInput, context: ToolContext) -> ValidationResult:
        return ValidationResult.success()

    async def call(self, parsed_input: WebSearchInput, context: ToolContext) -> ToolResult:
        provider = context.metadata.get("web_search_provider")
        if callable(provider):
            result = provider(parsed_input.query, parsed_input.max_results)
            search_results = list(await result) if inspect.isawaitable(result) else list(result)
        else:
            search_results = await self._search_default_provider(parsed_input.query, parsed_input.max_results)

        filtered = [
            item
            for item in search_results
            if self._passes_domain_filters(item.url, parsed_input.domains, parsed_input.blocked_domains)
        ][: parsed_input.max_results]
        if not filtered:
            return ToolResult(content="No web search results found")

        lines: list[str] = [f'Query: "{parsed_input.query}"', "Results:"]
        for index, item in enumerate(filtered, start=1):
            lines.append(f"{index}. {item.title}")
            lines.append(f"   URL: {item.url}")
            if item.snippet:
                lines.append(f"   Snippet: {item.snippet}")
        return ToolResult(
            content="\n".join(lines),
            metadata={
                "results": [
                    {
                        "title": item.title,
                        "url": item.url,
                        "snippet": item.snippet,
                    }
                    for item in filtered
                ]
            },
        )

    async def _search_default_provider(self, query: str, max_results: int) -> list[SearchResult]:
        search_url = f"{DEFAULT_WEB_SEARCH_URL}?{urllib_parse.urlencode({'q': query})}"
        html, _ = await fetch_raw_text(search_url)
        return self._parse_duckduckgo_results(html)[:max_results]

    def _parse_domains(self, value: Any) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValueError("domain filters must be a list of strings")
        cleaned = [item.lower().strip() for item in value if item.strip()]
        return cleaned or None

    def _passes_domain_filters(
        self,
        url: str,
        allowed_domains: list[str] | None,
        blocked_domains: list[str] | None,
    ) -> bool:
        hostname = urllib_parse.urlparse(url).hostname or ""
        lowered = hostname.lower()
        if blocked_domains and any(lowered == domain or lowered.endswith(f".{domain}") for domain in blocked_domains):
            return False
        if allowed_domains:
            return any(lowered == domain or lowered.endswith(f".{domain}") for domain in allowed_domains)
        return True

    def _parse_duckduckgo_results(self, html: str) -> list[SearchResult]:
        link_pattern = re.compile(
            r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
            re.IGNORECASE | re.DOTALL,
        )
        snippet_pattern = re.compile(
            r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(?P<snippet>.*?)</a>|'
            r'<div[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(?P<divsnippet>.*?)</div>',
            re.IGNORECASE | re.DOTALL,
        )
        links = list(link_pattern.finditer(html))
        snippets = list(snippet_pattern.finditer(html))
        results: list[SearchResult] = []
        for index, match in enumerate(links):
            url = unescape(match.group("url"))
            title = strip_html_fragment(match.group("title"))
            snippet_match = snippets[index] if index < len(snippets) else None
            snippet = ""
            if snippet_match is not None:
                snippet = strip_html_fragment(
                    snippet_match.group("snippet") or snippet_match.group("divsnippet") or ""
                )
            if title and url:
                results.append(SearchResult(title=title, url=url, snippet=snippet))
        return results
