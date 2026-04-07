from __future__ import annotations

import unittest
from dataclasses import dataclass, field
from typing import Any

from unified_assist.llm.anthropic_adapter import AnthropicConfig, AnthropicMessagesAdapter
from unified_assist.llm.base import (
    AssistantDeltaEvent,
    AssistantMessageStartEvent,
    AssistantMessageStopEvent,
    AssistantToolUseEvent,
    GenerationRequest,
    HttpRequest,
    ReplayModelAdapter,
)
from unified_assist.llm.minimax_adapter import MiniMaxAdapter, MiniMaxConfig
from unified_assist.llm.openai_adapter import OpenAIChatAdapter, OpenAICompatibleAdapter, OpenAIConfig
from unified_assist.messages.models import UserMessage
from unified_assist.tools.base import ToolSpec


@dataclass
class FakeTransport:
    response: dict[str, Any]
    requests: list[HttpRequest] = field(default_factory=list)

    async def send(self, request: HttpRequest) -> dict[str, Any]:
        self.requests.append(request)
        return self.response


class LlmAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_openai_adapter_builds_payload_and_parses_tool_calls(self) -> None:
        transport = FakeTransport(
            response={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": "Checking that now.",
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": "{\"path\": \"app.py\"}",
                                    },
                                }
                            ],
                        },
                    }
                ]
            }
        )
        adapter = OpenAIChatAdapter(OpenAIConfig(model="gpt-test", api_key="secret"), transport=transport)
        response = await adapter.generate(
            GenerationRequest(
                system_prompt="system prompt",
                messages=[UserMessage(content="Inspect the file")],
                tools=[ToolSpec(name="read_file", description="Read", input_schema={"type": "object"})],
            )
        )
        self.assertEqual(response.stop_reason, "tool_calls")
        self.assertEqual(response.assistant_blocks[0].text, "Checking that now.")
        self.assertEqual(response.assistant_blocks[1].name, "read_file")
        self.assertEqual(response.assistant_blocks[1].input["path"], "app.py")
        body = transport.requests[0].body
        self.assertEqual(body["model"], "gpt-test")
        self.assertEqual(body["messages"][0]["role"], "system")
        self.assertEqual(body["tools"][0]["function"]["name"], "read_file")

    async def test_openai_adapter_stream_generate_emits_canonical_events(self) -> None:
        transport = FakeTransport(
            response={
                "choices": [
                    {
                        "finish_reason": "tool_calls",
                        "message": {
                            "content": [
                                {"type": "text", "text": "Check"},
                                {"type": "text", "text": "ing"},
                            ],
                            "tool_calls": [
                                {
                                    "id": "call-1",
                                    "type": "function",
                                    "function": {
                                        "name": "read_file",
                                        "arguments": "{\"path\": \"app.py\"}",
                                    },
                                }
                            ],
                        },
                    }
                ]
            }
        )
        adapter = OpenAIChatAdapter(OpenAIConfig(model="gpt-test"), transport=transport)
        events = [
            event
            async for event in adapter.stream_generate(
                GenerationRequest(
                    system_prompt="system prompt",
                    messages=[UserMessage(content="Inspect the file")],
                    tools=[ToolSpec(name="read_file", description="Read", input_schema={"type": "object"})],
                )
            )
        ]
        self.assertIsInstance(events[0], AssistantMessageStartEvent)
        self.assertIsInstance(events[1], AssistantDeltaEvent)
        self.assertEqual(events[1].delta, "Check")
        self.assertIsInstance(events[2], AssistantDeltaEvent)
        self.assertEqual(events[2].delta, "ing")
        self.assertIsInstance(events[3], AssistantToolUseEvent)
        self.assertEqual(events[3].name, "read_file")
        self.assertIsInstance(events[4], AssistantMessageStopEvent)
        self.assertEqual(events[4].stop_reason, "tool_calls")

    async def test_openai_compatible_adapter_uses_custom_endpoint(self) -> None:
        transport = FakeTransport(response={"choices": [{"finish_reason": "stop", "message": {"content": "done"}}]})
        adapter = OpenAICompatibleAdapter(
            OpenAIConfig(
                model="qwen-test",
                base_url="http://localhost:8000/v1/chat/completions",
                provider_name="compatible",
                headers={"X-Test": "1"},
            ),
            transport=transport,
        )
        result = await adapter.generate(
            GenerationRequest(system_prompt="sys", messages=[UserMessage(content="hi")], tools=[])
        )
        self.assertEqual(result.assistant_blocks[0].text, "done")
        self.assertEqual(transport.requests[0].url, "http://localhost:8000/v1/chat/completions")
        self.assertEqual(transport.requests[0].headers["X-Test"], "1")
        self.assertEqual(transport.requests[0].headers["X-Provider"], "compatible")

    async def test_anthropic_adapter_builds_payload_and_parses_tool_use(self) -> None:
        transport = FakeTransport(
            response={
                "stop_reason": "tool_use",
                "content": [
                    {"type": "text", "text": "Let me check."},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "glob_search",
                        "input": {"pattern": "*.py"},
                    },
                ],
            }
        )
        adapter = AnthropicMessagesAdapter(
            AnthropicConfig(model="claude-test", api_key="secret"),
            transport=transport,
        )
        response = await adapter.generate(
            GenerationRequest(
                system_prompt="system prompt",
                messages=[UserMessage(content="Find python files")],
                tools=[ToolSpec(name="glob_search", description="Find files", input_schema={"type": "object"})],
            )
        )
        self.assertEqual(response.stop_reason, "tool_use")
        self.assertEqual(response.assistant_blocks[0].text, "Let me check.")
        self.assertEqual(response.assistant_blocks[1].name, "glob_search")
        body = transport.requests[0].body
        self.assertEqual(body["system"], "system prompt")
        self.assertEqual(body["messages"][0]["role"], "user")
        self.assertEqual(body["tools"][0]["name"], "glob_search")

    async def test_replay_model_adapter_collects_stream_events_into_response(self) -> None:
        adapter = ReplayModelAdapter(
            [
                [
                    AssistantMessageStartEvent(),
                    AssistantDeltaEvent(delta="All "),
                    AssistantDeltaEvent(delta="done"),
                    AssistantToolUseEvent(name="think", input={"note": "x"}, tool_use_id="tool-1"),
                    AssistantMessageStopEvent(stop_reason="tool_calls"),
                ]
            ]
        )
        response = await adapter.generate(
            GenerationRequest(
                system_prompt="sys",
                messages=[UserMessage(content="hi")],
                tools=[ToolSpec(name="think", description="Think", input_schema={"type": "object"})],
            )
        )
        self.assertEqual(response.stop_reason, "tool_calls")
        self.assertEqual(response.assistant_blocks[0].text, "All done")
        self.assertEqual(response.assistant_blocks[1].name, "think")

    async def test_minimax_adapter_sets_reasoning_split_and_parses_reasoning(self) -> None:
        transport = FakeTransport(
            response={
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "reasoning_details": [
                                {"text": "Need a short confirmation."},
                            ],
                            "content": "MiniMax connected.",
                        },
                    }
                ]
            }
        )
        adapter = MiniMaxAdapter(MiniMaxConfig(api_key="secret"))
        adapter.transport = transport
        response = await adapter.generate(
            GenerationRequest(
                system_prompt="sys",
                messages=[UserMessage(content="hi")],
                tools=[],
            )
        )
        self.assertEqual(response.assistant_blocks[0].type, "thinking")
        self.assertEqual(response.assistant_blocks[0].text, "Need a short confirmation.")
        self.assertEqual(response.assistant_blocks[1].text, "MiniMax connected.")
        self.assertEqual(transport.requests[0].url, "https://api.minimaxi.com/v1/chat/completions")
        self.assertEqual(transport.requests[0].headers["X-Provider"], "minimax")
        self.assertEqual(transport.requests[0].body["reasoning_split"], True)

    async def test_minimax_adapter_normalizes_root_base_url(self) -> None:
        transport = FakeTransport(response={"choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]})
        adapter = MiniMaxAdapter(MiniMaxConfig(api_key="secret", base_url="https://api.minimaxi.com/v1"))
        adapter.transport = transport
        await adapter.generate(
            GenerationRequest(
                system_prompt="sys",
                messages=[UserMessage(content="hi")],
                tools=[],
            )
        )
        self.assertEqual(transport.requests[0].url, "https://api.minimaxi.com/v1/chat/completions")


if __name__ == "__main__":
    unittest.main()
