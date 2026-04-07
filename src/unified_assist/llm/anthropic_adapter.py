from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from unified_assist.llm.base import (
    GenerationEvent,
    GenerationRequest,
    GenerationResponse,
    HttpRequest,
    JsonTransport,
    UrllibJsonTransport,
    collect_stream_response,
)
from unified_assist.llm.stream_parser import (
    anthropic_content_to_events,
    messages_to_anthropic_payload,
    tools_to_anthropic_payload,
)


@dataclass(slots=True)
class AnthropicConfig:
    model: str
    api_key: str = ""
    base_url: str = "https://api.anthropic.com/v1/messages"
    anthropic_version: str = "2023-06-01"
    max_tokens: int = 4096
    headers: dict[str, str] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)


class AnthropicMessagesAdapter:
    def __init__(self, config: AnthropicConfig, transport: JsonTransport | None = None) -> None:
        self.config = config
        self.transport = transport or UrllibJsonTransport()

    def stream_generate(self, request: GenerationRequest) -> AsyncIterator[GenerationEvent]:
        async def _stream() -> AsyncIterator[GenerationEvent]:
            body: dict[str, Any] = {
                "model": request.metadata.get("model", self.config.model),
                "system": request.system_prompt,
                "messages": messages_to_anthropic_payload(request.messages),
                "max_tokens": request.metadata.get("max_tokens", self.config.max_tokens),
            }
            if request.tools:
                body["tools"] = tools_to_anthropic_payload(request.tools)
            body.update(self.config.extra_body)

            headers = {
                "anthropic-version": self.config.anthropic_version,
                **self.config.headers,
            }
            if self.config.api_key:
                headers["x-api-key"] = self.config.api_key

            data = await self.transport.send(
                HttpRequest(
                    url=self.config.base_url,
                    headers=headers,
                    body=body,
                )
            )

            if "error" in data:
                error = data["error"]
                message = error["message"] if isinstance(error, dict) else str(error)
                for event in anthropic_content_to_events(
                    [],
                    stop_reason="error",
                    raw=data,
                    is_error=True,
                    error_message=str(message),
                ):
                    yield event
                return

            for event in anthropic_content_to_events(
                data.get("content", []),
                stop_reason=data.get("stop_reason"),
                raw=data,
            ):
                yield event

        return _stream()

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        return await collect_stream_response(self.stream_generate(request))
