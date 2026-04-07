from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol
from urllib.error import HTTPError
from urllib import request as urllib_request

from unified_assist.messages.blocks import AssistantBlock, TextBlock, ThinkingBlock, ToolUseBlock
from unified_assist.messages.models import Message
from unified_assist.tools.base import ToolSpec


@dataclass(slots=True)
class GenerationRequest:
    system_prompt: str
    messages: list[Message]
    tools: list[ToolSpec]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class GenerationResponse:
    assistant_blocks: list[AssistantBlock]
    stop_reason: str | None = None
    is_error: bool = False
    raw: Any = None


@dataclass(frozen=True, slots=True)
class AssistantMessageStartEvent:
    raw: Any = None
    type: str = field(init=False, default="assistant_message_start")


@dataclass(frozen=True, slots=True)
class AssistantDeltaEvent:
    delta: str
    block_type: Literal["text", "thinking"] = "text"
    raw: Any = None
    type: str = field(init=False, default="assistant_delta")


@dataclass(frozen=True, slots=True)
class AssistantToolUseEvent:
    name: str
    input: dict[str, Any]
    tool_use_id: str
    raw: Any = None
    type: str = field(init=False, default="assistant_tool_use")


@dataclass(frozen=True, slots=True)
class AssistantErrorEvent:
    message: str
    stop_reason: str = "error"
    raw: Any = None
    type: str = field(init=False, default="assistant_error")


@dataclass(frozen=True, slots=True)
class AssistantMessageStopEvent:
    stop_reason: str | None = None
    raw: Any = None
    type: str = field(init=False, default="assistant_message_stop")


GenerationEvent = (
    AssistantMessageStartEvent
    | AssistantDeltaEvent
    | AssistantToolUseEvent
    | AssistantErrorEvent
    | AssistantMessageStopEvent
)


@dataclass(frozen=True, slots=True)
class HttpRequest:
    url: str
    headers: dict[str, str]
    body: dict[str, Any]
    method: str = "POST"
    timeout: float = 60.0


class JsonTransport(Protocol):
    async def send(self, request: HttpRequest) -> dict[str, Any]:
        """Send a JSON request and return the decoded JSON response."""


class UrllibJsonTransport:
    async def send(self, request: HttpRequest) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="claw-http") as executor:
            return await loop.run_in_executor(executor, self._send_sync, request)

    def _send_sync(self, request: HttpRequest) -> dict[str, Any]:
        encoded = json.dumps(request.body).encode("utf-8")
        raw_request = urllib_request.Request(
            url=request.url,
            headers={
                **request.headers,
                "Content-Type": "application/json",
            },
            data=encoded,
            method=request.method,
        )
        try:
            with urllib_request.urlopen(raw_request, timeout=request.timeout) as response:
                payload = response.read().decode("utf-8")
        except HTTPError as exc:
            payload = exc.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                data = {"error": {"message": payload or str(exc), "code": exc.code}}
            if isinstance(data, dict):
                data.setdefault("error", {"message": payload or str(exc), "code": exc.code})
                return data
            return {"error": {"message": payload or str(exc), "code": exc.code}}
        return json.loads(payload)


class ModelAdapter(Protocol):
    def stream_generate(self, request: GenerationRequest) -> AsyncIterator[GenerationEvent]:
        """Yield canonical assistant events for the next turn."""

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        """Generate the next assistant turn."""


class ReplayModelAdapter:
    """Deterministic adapter for unit tests and local demos."""

    def __init__(self, responses: list[GenerationResponse | list[GenerationEvent]]) -> None:
        self._responses = list(responses)
        self.requests: list[GenerationRequest] = []

    def stream_generate(self, request: GenerationRequest) -> AsyncIterator[GenerationEvent]:
        async def _stream() -> AsyncIterator[GenerationEvent]:
            self.requests.append(request)
            if not self._responses:
                raise RuntimeError("no replay response left")
            response = self._responses.pop(0)
            for event in normalize_to_events(response):
                yield event

        return _stream()

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        self.requests.append(request)
        if not self._responses:
            raise RuntimeError("no replay response left")
        response = self._responses.pop(0)
        if isinstance(response, GenerationResponse):
            return response
        return await collect_stream_response(_iter_events(response))


async def _iter_events(events: list[GenerationEvent]) -> AsyncIterator[GenerationEvent]:
    for event in events:
        yield event


def _merge_delta_into_blocks(
    blocks: list[AssistantBlock], block_type: Literal["text", "thinking"], delta: str
) -> None:
    if not delta:
        return
    if block_type == "text":
        if blocks and isinstance(blocks[-1], TextBlock):
            blocks[-1] = TextBlock(text=blocks[-1].text + delta)
            return
        blocks.append(TextBlock(text=delta))
        return
    if blocks and isinstance(blocks[-1], ThinkingBlock):
        blocks[-1] = ThinkingBlock(text=blocks[-1].text + delta)
        return
    blocks.append(ThinkingBlock(text=delta))


async def collect_stream_response(stream: AsyncIterator[GenerationEvent]) -> GenerationResponse:
    blocks: list[AssistantBlock] = []
    raw_events: list[Any] = []
    stop_reason: str | None = None
    is_error = False
    async for event in stream:
        if event.raw is not None:
            raw_events.append(event.raw)
        if isinstance(event, AssistantDeltaEvent):
            _merge_delta_into_blocks(blocks, event.block_type, event.delta)
        elif isinstance(event, AssistantToolUseEvent):
            blocks.append(
                ToolUseBlock(
                    name=event.name,
                    input=dict(event.input),
                    tool_use_id=event.tool_use_id,
                )
            )
        elif isinstance(event, AssistantErrorEvent):
            is_error = True
            _merge_delta_into_blocks(blocks, "text", event.message)
            stop_reason = event.stop_reason
        elif isinstance(event, AssistantMessageStopEvent):
            stop_reason = event.stop_reason
    return GenerationResponse(
        assistant_blocks=blocks,
        stop_reason=stop_reason,
        is_error=is_error,
        raw=raw_events or None,
    )


def response_to_events(response: GenerationResponse) -> list[GenerationEvent]:
    events: list[GenerationEvent] = [AssistantMessageStartEvent(raw=response.raw)]
    if response.is_error:
        message = ""
        for block in response.assistant_blocks:
            if isinstance(block, (TextBlock, ThinkingBlock)):
                message += block.text
        events.append(
            AssistantErrorEvent(
                message=message or "error",
                stop_reason=response.stop_reason or "error",
                raw=response.raw,
            )
        )
    else:
        for block in response.assistant_blocks:
            if isinstance(block, TextBlock):
                events.append(AssistantDeltaEvent(delta=block.text, block_type="text"))
            elif isinstance(block, ThinkingBlock):
                events.append(AssistantDeltaEvent(delta=block.text, block_type="thinking"))
            elif isinstance(block, ToolUseBlock):
                events.append(
                    AssistantToolUseEvent(
                        name=block.name,
                        input=dict(block.input),
                        tool_use_id=block.tool_use_id,
                    )
                )
    events.append(AssistantMessageStopEvent(stop_reason=response.stop_reason, raw=response.raw))
    return events


def normalize_to_events(
    response: GenerationResponse | list[GenerationEvent],
) -> list[GenerationEvent]:
    if isinstance(response, GenerationResponse):
        return response_to_events(response)
    return list(response)
