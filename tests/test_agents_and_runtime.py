from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_assist.agents.definitions import GENERAL_PURPOSE_AGENT
from unified_assist.agents.forking import build_fork_messages, is_fork_child
from unified_assist.agents.registry import AgentRegistry
from unified_assist.agents.runtime import AgentRuntime
from unified_assist.llm.base import GenerationResponse, ReplayModelAdapter
from unified_assist.memory.manager import MemoryManager
from unified_assist.memory.store import MemoryStore
from unified_assist.messages.blocks import TextBlock, ToolUseBlock
from unified_assist.messages.models import UserMessage
from unified_assist.prompt.builder import PromptBuilder
from unified_assist.runtime.attachments import build_agent_attachment
from unified_assist.runtime.cancellation import CancellationScope
from unified_assist.runtime.events import EventBus
from unified_assist.runtime.services import RuntimeServices
from unified_assist.stability.transcript_store import TranscriptStore
from unified_assist.tools.base import ToolContext
from unified_assist.tools.builtins.agent import AgentTool
from unified_assist.tools.builtins.think import ThinkTool
from unified_assist.tools.executor import ToolExecutor
from unified_assist.tools.registry import ToolRegistry
from unified_assist.tools.result_store import ToolResultStore


class AgentAndRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_registry_forking_and_runtime_primitives(self) -> None:
        registry = AgentRegistry.with_builtins()
        self.assertIn("general-purpose", registry.list_agent_types())
        forked = build_fork_messages([UserMessage(content="parent")], "Inspect this")
        self.assertTrue(is_fork_child(forked))

        scope = CancellationScope()
        child = scope.child()
        scope.cancel()
        self.assertTrue(child.cancelled)

        bus = EventBus()
        bus.emit("agent_started", agent_type="general-purpose")
        attachment = build_agent_attachment(
            agent_name="general-purpose",
            transition_reason="completed",
            summary="done",
        )
        self.assertEqual(bus.events[0].kind, "agent_started")
        self.assertEqual(attachment.data["summary"], "done")

    async def test_agent_runtime_and_agent_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = Path(tmp)
            tool_registry = ToolRegistry()
            tool_registry.register(ThinkTool())
            tool_registry.register(AgentTool())
            result_store = ToolResultStore(cwd / ".assist" / "tool_results")
            tool_executor = ToolExecutor(tool_registry, result_store)
            model = ReplayModelAdapter(
                [
                    GenerationResponse(assistant_blocks=[TextBlock(text="Child complete")]),
                    GenerationResponse(assistant_blocks=[TextBlock(text="Delegated child complete")]),
                ]
            )
            services = RuntimeServices(
                model=model,
                prompt_builder=PromptBuilder(),
                tool_executor=tool_executor,
                memory_manager=MemoryManager(MemoryStore(cwd / ".assist" / "memory")),
                skills=[],
                transcript_store=TranscriptStore(cwd / ".assist" / "transcripts"),
                agent_registry=AgentRegistry.with_builtins(),
            )
            runtime = AgentRuntime(services)
            parent_context = ToolContext(cwd=cwd, metadata={"runtime_services": services, "messages": [UserMessage(content="parent task")]})
            run_result = await runtime.run(
                agent_definition=GENERAL_PURPOSE_AGENT,
                task_prompt="Do the thing",
                parent_messages=[UserMessage(content="parent task")],
                parent_context=parent_context,
                description="subtask",
            )
            self.assertEqual(run_result.summary, "Child complete")
            self.assertEqual(run_result.state.transition_reason, "completed")
            self.assertEqual(services.event_bus.events[0].kind, "agent_started")

            agent_tool = AgentTool()
            tool_result = await agent_tool.call(
                agent_tool.parse_input(
                    {
                        "prompt": "Solve subtask",
                        "description": "delegate",
                        "agent_type": "general-purpose",
                    }
                ),
                parent_context,
            )
            self.assertIn("Agent general-purpose completed", tool_result.content)
            self.assertIn("Delegated child complete", tool_result.content)
            self.assertEqual(tool_result.metadata["agent_type"], "general-purpose")

    async def test_agent_tool_unknown_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            context = ToolContext(cwd=Path(tmp), metadata={})
            result = await AgentTool().call(
                AgentTool().parse_input({"prompt": "x", "description": "y", "agent_type": "missing"}),
                context,
            )
            self.assertTrue(result.is_error)


if __name__ == "__main__":
    unittest.main()
