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
    messages_to_openai_payload,
    openai_message_to_events,
    tools_to_openai_payload,
)


@dataclass(slots=True)
class OpenAIConfig:
    model: str
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1/chat/completions"
    provider_name: str = "openai"
    headers: dict[str, str] = field(default_factory=dict)
    extra_body: dict[str, Any] = field(default_factory=dict)


class OpenAIChatAdapter:
    def __init__(self, config: OpenAIConfig, transport: JsonTransport | None = None) -> None:
        self.config = config
        self.transport = transport or UrllibJsonTransport()

    def stream_generate(self, request: GenerationRequest) -> AsyncIterator[GenerationEvent]:
        async def _stream() -> AsyncIterator[GenerationEvent]:
            body: dict[str, Any] = {
                "model": request.metadata.get("model", self.config.model),
                "messages": messages_to_openai_payload(request.system_prompt, request.messages),
            }
            if request.tools:
                body["tools"] = tools_to_openai_payload(request.tools)
                body["tool_choice"] = "auto"
            body.update(self.config.extra_body)

            headers = dict(self.config.headers)
            if self.config.api_key:
                headers["Authorization"] = f"Bearer {self.config.api_key}"
            headers["X-Provider"] = self.config.provider_name

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
                for event in openai_message_to_events(
                    {"content": str(message)},
                    stop_reason="error",
                    raw=data,
                    is_error=True,
                ):
                    yield event
                return

            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message", {})
            for event in openai_message_to_events(
                message,
                stop_reason=choice.get("finish_reason"),
                raw=data,
            ):
                yield event

        return _stream()

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        return await collect_stream_response(self.stream_generate(request))


class OpenAICompatibleAdapter(OpenAIChatAdapter):
    """OpenAI-style API adapter for compatible providers such as local gateways or hosted compatibles."""
