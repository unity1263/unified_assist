from __future__ import annotations

import io
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from unified_assist.llm.base import (
    GenerationRequest,
    GenerationResponse,
    HttpRequest,
    ReplayModelAdapter,
    UrllibJsonTransport,
)
from unified_assist.messages.blocks import TextBlock, ToolResultBlock, ToolUseBlock, block_from_dict
from unified_assist.messages.models import (
    AssistantMessage,
    ToolResultMessage,
    UserMessage,
    message_from_dict,
    message_to_dict,
)
from unified_assist.messages.normalize import deserialize_messages, drop_empty_assistant_messages, last_user_text, serialize_messages


class MessagesAndLlmTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocks_and_messages_roundtrip(self) -> None:
        block = ToolUseBlock(name="read_file", input={"path": "a.txt"}, tool_use_id="call-1")
        self.assertEqual(block_from_dict(block.to_dict()), block)

        message = ToolResultMessage(
            results=[ToolResultBlock(tool_use_id="call-1", content="done")],
            source_tool="write_file",
            metadata={"persisted_path": "/tmp/x"},
        )
        restored = message_from_dict(message_to_dict(message))
        self.assertEqual(restored.source_tool, "write_file")
        self.assertEqual(restored.metadata["persisted_path"], "/tmp/x")

    async def test_normalize_helpers(self) -> None:
        messages = [
            UserMessage(content="hello"),
            AssistantMessage(blocks=[]),
            AssistantMessage(blocks=[TextBlock(text="")]),
            AssistantMessage(blocks=[TextBlock(text="world")]),
        ]
        filtered = drop_empty_assistant_messages(messages)
        self.assertEqual(len(filtered), 2)
        self.assertEqual(last_user_text(filtered), "hello")
        serialized = serialize_messages(filtered)
        self.assertEqual(len(deserialize_messages(serialized)), 2)

    async def test_replay_model_adapter(self) -> None:
        adapter = ReplayModelAdapter([GenerationResponse(assistant_blocks=[TextBlock(text="done")])])
        request = GenerationRequest(system_prompt="sys", messages=[], tools=["think"])
        response = await adapter.generate(request)
        self.assertEqual(response.assistant_blocks[0].text, "done")
        self.assertEqual(adapter.requests[0].system_prompt, "sys")

    async def test_urllib_transport_returns_error_body_on_http_error(self) -> None:
        transport = UrllibJsonTransport()
        error = HTTPError(
            url="https://example.com",
            code=401,
            msg="Unauthorized",
            hdrs=None,
            fp=io.BytesIO(b'{"error":{"message":"bad api key","code":"unauthorized"}}'),
        )
        with patch("unified_assist.llm.base.urllib_request.urlopen", side_effect=error):
            response = await transport.send(
                HttpRequest(
                    url="https://example.com",
                    headers={},
                    body={"x": 1},
                )
            )
        self.assertEqual(response["error"]["message"], "bad api key")


if __name__ == "__main__":
    unittest.main()
