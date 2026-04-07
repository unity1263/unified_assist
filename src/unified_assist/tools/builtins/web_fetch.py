from __future__ import annotations

import inspect
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, ClassVar, Mapping

from unified_assist.tools.base import BaseTool, ToolContext, ToolResult, ValidationResult
from unified_assist.tools.builtins.web_common import FetchedPage, fetch_url, normalize_url


WebFetchTransport = Callable[..., FetchedPage | Awaitable[FetchedPage]]


@dataclass(slots=True)
class WebFetchInput:
    url: str
    prompt: str = ""
    max_chars: int = 12000


class WebFetchTool(BaseTool[WebFetchInput]):
    name = "WebFetch"
    description = "Fetch a web page and return extracted text content for the model to analyze"
    _cache: ClassVar[dict[str, tuple[float, FetchedPage]]] = {}
    _cache_ttl_seconds: ClassVar[int] = 15 * 60

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "prompt": {"type": "string"},
                "max_chars": {"type": "integer", "minimum": 500},
            },
            "required": ["url"],
            "additionalProperties": False,
        }

    def parse_input(self, raw_input: Mapping[str, Any]) -> WebFetchInput:
        url = raw_input.get("url")
        prompt = raw_input.get("prompt", "")
        max_chars = raw_input.get("max_chars", 12000)
        if not isinstance(url, str) or not url.strip():
            raise ValueError("url must be a non-empty string")
        if not isinstance(prompt, str):
            raise ValueError("prompt must be a string")
        if not isinstance(max_chars, int) or max_chars < 500:
            raise ValueError("max_chars must be an integer >= 500")
        return WebFetchInput(url=url.strip(), prompt=prompt.strip(), max_chars=max_chars)

    def is_read_only(self, parsed_input: WebFetchInput) -> bool:
        return True

    def is_concurrency_safe(self, parsed_input: WebFetchInput) -> bool:
        return True

    async def validate(self, parsed_input: WebFetchInput, context: ToolContext) -> ValidationResult:
        try:
            normalize_url(parsed_input.url)
        except ValueError as exc:
            return ValidationResult.failure(str(exc))
        return ValidationResult.success()

    async def call(self, parsed_input: WebFetchInput, context: ToolContext) -> ToolResult:
        normalized_url = normalize_url(parsed_input.url)
        page = await self._get_page(normalized_url, context=context, max_chars=parsed_input.max_chars)
        lines = [
            f"Requested URL: {parsed_input.url}",
            f"Final URL: {page.final_url}",
            f"Status: {page.status_code}",
            f"Content-Type: {page.content_type}",
        ]
        if page.title:
            lines.append(f"Title: {page.title}")
        if parsed_input.prompt:
            lines.append(f"Requested extraction: {parsed_input.prompt}")
        lines.extend(["Content:", page.content])
        return ToolResult(
            content="\n".join(lines).strip(),
            metadata={
                "url": page.final_url,
                "status_code": page.status_code,
                "title": page.title,
                "content_type": page.content_type,
            },
        )

    async def _get_page(
        self,
        normalized_url: str,
        *,
        context: ToolContext,
        max_chars: int,
    ) -> FetchedPage:
        now = time.time()
        cached = self._cache.get(normalized_url)
        if cached and cached[0] > now:
            return cached[1]
        transport = context.metadata.get("web_fetch_transport")
        if callable(transport):
            result = transport(normalized_url, max_chars=max_chars)
            page = await result if inspect.isawaitable(result) else result
        else:
            page = await fetch_url(normalized_url, max_chars=max_chars)
        self._cache[normalized_url] = (now + self._cache_ttl_seconds, page)
        return page
