from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib import parse as urllib_parse
from urllib import request as urllib_request


DEFAULT_USER_AGENT = "unified_assist/0.1 (+https://github.com/anthropic/claude-code)"


@dataclass(frozen=True, slots=True)
class FetchedPage:
    requested_url: str
    final_url: str
    status_code: int
    content_type: str
    title: str
    content: str


@dataclass(frozen=True, slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""


class _HtmlTextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._title_parts: list[str] = []
        self._text_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    @property
    def title(self) -> str:
        return _normalize_whitespace("".join(self._title_parts))

    @property
    def text(self) -> str:
        return _normalize_whitespace(" ".join(self._text_parts))

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return
        if tag == "title":
            self._in_title = True
        if tag in {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._text_parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
            return
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self._title_parts.append(data)
        self._text_parts.append(data)


def normalize_url(url: str) -> str:
    parsed = urllib_parse.urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("url must use http or https")
    if parsed.scheme == "http" and _should_upgrade_to_https(parsed.hostname):
        parsed = parsed._replace(scheme="https")
    return urllib_parse.urlunparse(parsed)


async def fetch_url(
    url: str,
    *,
    timeout: float = 20.0,
    max_chars: int = 12000,
    headers: dict[str, str] | None = None,
) -> FetchedPage:
    return await asyncio.to_thread(
        _fetch_url_sync,
        url,
        timeout=timeout,
        max_chars=max_chars,
        headers=headers or {},
    )


async def fetch_raw_text(
    url: str,
    *,
    timeout: float = 20.0,
    headers: dict[str, str] | None = None,
) -> tuple[str, str]:
    return await asyncio.to_thread(
        _fetch_raw_text_sync,
        url,
        timeout=timeout,
        headers=headers or {},
    )


def extract_text_from_html(html: str, *, max_chars: int = 12000) -> tuple[str, str]:
    parser = _HtmlTextExtractor()
    parser.feed(html)
    title = parser.title
    content = clip_text(parser.text or _strip_tags(html), max_chars=max_chars)
    return title, content


def clip_text(text: str, *, max_chars: int) -> str:
    normalized = _normalize_whitespace(text)
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max(0, max_chars - 3)].rstrip() + "..."


def strip_html_fragment(fragment: str) -> str:
    return _normalize_whitespace(_strip_tags(fragment))


def _fetch_url_sync(
    url: str,
    *,
    timeout: float,
    max_chars: int,
    headers: dict[str, str],
) -> FetchedPage:
    request = urllib_request.Request(
        url=url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            **headers,
        },
        method="GET",
    )
    with urllib_request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        final_url = response.geturl()
        status_code = getattr(response, "status", 200)
        content_type = response.headers.get("Content-Type", "text/plain")
        charset = response.headers.get_content_charset() or "utf-8"
    text = raw.decode(charset, errors="replace")
    if "html" in content_type.lower():
        title, content = extract_text_from_html(text, max_chars=max_chars)
    else:
        title = ""
        content = clip_text(text, max_chars=max_chars)
    return FetchedPage(
        requested_url=url,
        final_url=final_url,
        status_code=status_code,
        content_type=content_type,
        title=title,
        content=content,
    )


def _fetch_raw_text_sync(
    url: str,
    *,
    timeout: float,
    headers: dict[str, str],
) -> tuple[str, str]:
    request = urllib_request.Request(
        url=url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            **headers,
        },
        method="GET",
    )
    with urllib_request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
        final_url = response.geturl()
        charset = response.headers.get_content_charset() or "utf-8"
    return raw.decode(charset, errors="replace"), final_url


def _strip_tags(text: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", text)
    return unescape(without_tags)


def _normalize_whitespace(text: str) -> str:
    collapsed = re.sub(r"[ \t\r\f\v]+", " ", text)
    collapsed = re.sub(r"\n{3,}", "\n\n", collapsed)
    lines = [line.strip() for line in collapsed.splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _should_upgrade_to_https(hostname: str | None) -> bool:
    if not hostname:
        return False
    lowered = hostname.lower()
    return lowered not in {"localhost", "127.0.0.1", "0.0.0.0"} and not lowered.endswith(".local")
