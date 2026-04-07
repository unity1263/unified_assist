from __future__ import annotations

import json
from typing import Any

from unified_assist.llm.base import (
    AssistantDeltaEvent,
    AssistantErrorEvent,
    AssistantMessageStartEvent,
    AssistantMessageStopEvent,
    AssistantToolUseEvent,
    GenerationEvent,
)
from unified_assist.messages.blocks import TextBlock, ThinkingBlock, ToolUseBlock
from unified_assist.messages.models import AssistantMessage, Message, SystemMessage, ToolResultMessage, UserMessage
from unified_assist.tools.base import ToolSpec


def _safe_json_loads(text: str) -> dict[str, Any]:
    try:
        loaded = json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}
    return loaded if isinstance(loaded, dict) else {"value": loaded}


def _reasoning_texts(message: dict[str, Any]) -> list[str]:
    raw = message.get("reasoning_details")
    texts: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    texts.append(text)
            elif isinstance(item, str) and item.strip():
                texts.append(item)
    elif isinstance(raw, dict):
        text = raw.get("text")
        if isinstance(text, str) and text.strip():
            texts.append(text)

    fallback = message.get("reasoning_content")
    if isinstance(fallback, str) and fallback.strip():
        texts.append(fallback)
    return texts


def tools_to_openai_payload(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
        for tool in tools
    ]


def messages_to_openai_payload(system_prompt: str, messages: list[Message]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
    for message in messages:
        if isinstance(message, SystemMessage):
            payload.append({"role": "system", "content": message.content})
        elif isinstance(message, UserMessage):
            payload.append({"role": "user", "content": message.content})
        elif isinstance(message, AssistantMessage):
            text_content = message.text or None
            tool_calls = [
                {
                    "id": block.tool_use_id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input, ensure_ascii=True),
                    },
                }
                for block in message.tool_uses
            ]
            item: dict[str, Any] = {"role": "assistant", "content": text_content}
            if tool_calls:
                item["tool_calls"] = tool_calls
            payload.append(item)
        elif isinstance(message, ToolResultMessage):
            for result in message.results:
                payload.append(
                    {
                        "role": "tool",
                        "tool_call_id": result.tool_use_id,
                        "content": result.content,
                    }
                )
    return payload


def openai_message_to_blocks(message: dict[str, Any]) -> list[TextBlock | ThinkingBlock | ToolUseBlock]:
    blocks: list[TextBlock | ThinkingBlock | ToolUseBlock] = []
    for reasoning_text in _reasoning_texts(message):
        blocks.append(ThinkingBlock(text=reasoning_text))
    content = message.get("content")
    if isinstance(content, str) and content:
        blocks.append(TextBlock(text=content))
    elif isinstance(content, list):
        for part in content:
            part_type = part.get("type")
            if part_type in {"text", "output_text"} and part.get("text"):
                blocks.append(TextBlock(text=str(part["text"])))
            elif part_type in {"thinking", "reasoning"} and part.get("text"):
                blocks.append(ThinkingBlock(text=str(part["text"])))

    for tool_call in message.get("tool_calls", []) or []:
        function = tool_call.get("function", {})
        arguments = function.get("arguments", "{}")
        parsed = _safe_json_loads(arguments) if isinstance(arguments, str) else {}
        blocks.append(
            ToolUseBlock(
                name=str(function.get("name", "")),
                input=parsed,
                tool_use_id=str(tool_call.get("id", "")),
            )
        )
    return blocks


def openai_message_to_events(
    message: dict[str, Any],
    *,
    stop_reason: str | None = None,
    raw: Any = None,
    is_error: bool = False,
) -> list[GenerationEvent]:
    events: list[GenerationEvent] = [AssistantMessageStartEvent(raw=raw)]
    if is_error:
        text = str(message.get("content", "error"))
        events.append(AssistantErrorEvent(message=text, stop_reason=stop_reason or "error", raw=raw))
        events.append(AssistantMessageStopEvent(stop_reason=stop_reason or "error", raw=raw))
        return events

    for reasoning_text in _reasoning_texts(message):
        events.append(AssistantDeltaEvent(delta=reasoning_text, block_type="thinking"))

    content = message.get("content")
    if isinstance(content, str) and content:
        events.append(AssistantDeltaEvent(delta=content, block_type="text"))
    elif isinstance(content, list):
        for part in content:
            part_type = part.get("type")
            if part_type in {"text", "output_text"} and part.get("text"):
                events.append(AssistantDeltaEvent(delta=str(part["text"]), block_type="text"))
            elif part_type in {"thinking", "reasoning"} and part.get("text"):
                events.append(AssistantDeltaEvent(delta=str(part["text"]), block_type="thinking"))

    for tool_call in message.get("tool_calls", []) or []:
        function = tool_call.get("function", {})
        arguments = function.get("arguments", "{}")
        parsed = _safe_json_loads(arguments) if isinstance(arguments, str) else {}
        events.append(
            AssistantToolUseEvent(
                name=str(function.get("name", "")),
                input=parsed,
                tool_use_id=str(tool_call.get("id", "")),
            )
        )
    events.append(AssistantMessageStopEvent(stop_reason=stop_reason, raw=raw))
    return events


def tools_to_anthropic_payload(tools: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }
        for tool in tools
    ]


def messages_to_anthropic_payload(messages: list[Message]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, UserMessage):
            payload.append({"role": "user", "content": [{"type": "text", "text": message.content}]})
        elif isinstance(message, AssistantMessage):
            content: list[dict[str, Any]] = []
            for block in message.blocks:
                if isinstance(block, TextBlock):
                    content.append({"type": "text", "text": block.text})
                elif isinstance(block, ThinkingBlock):
                    content.append({"type": "thinking", "text": block.text})
                elif isinstance(block, ToolUseBlock):
                    content.append(
                        {
                            "type": "tool_use",
                            "id": block.tool_use_id,
                            "name": block.name,
                            "input": block.input,
                        }
                    )
            payload.append({"role": "assistant", "content": content})
        elif isinstance(message, ToolResultMessage):
            content = [
                {
                    "type": "tool_result",
                    "tool_use_id": result.tool_use_id,
                    "content": result.content,
                    "is_error": result.is_error,
                }
                for result in message.results
            ]
            payload.append({"role": "user", "content": content})
    return payload


def anthropic_content_to_blocks(content: list[dict[str, Any]]) -> list[TextBlock | ThinkingBlock | ToolUseBlock]:
    blocks: list[TextBlock | ThinkingBlock | ToolUseBlock] = []
    for part in content:
        part_type = part.get("type")
        if part_type == "text":
            blocks.append(TextBlock(text=str(part.get("text", ""))))
        elif part_type == "thinking":
            blocks.append(ThinkingBlock(text=str(part.get("text", ""))))
        elif part_type == "tool_use":
            blocks.append(
                ToolUseBlock(
                    name=str(part.get("name", "")),
                    input=dict(part.get("input", {})),
                    tool_use_id=str(part.get("id", "")),
                )
            )
    return blocks


def anthropic_content_to_events(
    content: list[dict[str, Any]],
    *,
    stop_reason: str | None = None,
    raw: Any = None,
    is_error: bool = False,
    error_message: str = "error",
) -> list[GenerationEvent]:
    events: list[GenerationEvent] = [AssistantMessageStartEvent(raw=raw)]
    if is_error:
        events.append(
            AssistantErrorEvent(
                message=error_message,
                stop_reason=stop_reason or "error",
                raw=raw,
            )
        )
        events.append(AssistantMessageStopEvent(stop_reason=stop_reason or "error", raw=raw))
        return events

    for part in content:
        part_type = part.get("type")
        if part_type == "text":
            events.append(AssistantDeltaEvent(delta=str(part.get("text", "")), block_type="text"))
        elif part_type == "thinking":
            events.append(
                AssistantDeltaEvent(delta=str(part.get("text", "")), block_type="thinking")
            )
        elif part_type == "tool_use":
            events.append(
                AssistantToolUseEvent(
                    name=str(part.get("name", "")),
                    input=dict(part.get("input", {})),
                    tool_use_id=str(part.get("id", "")),
                )
            )
    events.append(AssistantMessageStopEvent(stop_reason=stop_reason, raw=raw))
    return events
