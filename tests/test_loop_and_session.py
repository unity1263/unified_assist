from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_assist.app.app_config import AppConfig
from unified_assist.app.session_engine import SessionEngine
from unified_assist.llm.base import (
    AssistantDeltaEvent,
    AssistantMessageStartEvent,
    AssistantMessageStopEvent,
    AssistantToolUseEvent,
    GenerationResponse,
    ReplayModelAdapter,
)
from unified_assist.loop.agent_loop import AgentLoop
from unified_assist.loop.state import LoopState
from unified_assist.loop.transitions import append_turn
from unified_assist.memory.manager import MemoryManager
from unified_assist.memory.store import MemoryStore
from unified_assist.messages.blocks import TextBlock, ToolUseBlock
from unified_assist.messages.models import AssistantMessage, UserMessage
from unified_assist.prompt.builder import PromptBuilder
from unified_assist.skills.models import Skill
from unified_assist.stability.token_budget import TokenBudget
from unified_assist.stability.transcript_store import TranscriptStore
from unified_assist.tools.base import ToolContext
from unified_assist.tools.builtins.write_file import WriteFileTool
from unified_assist.tools.executor import ToolExecutor
from unified_assist.tools.registry import ToolRegistry
from unified_assist.tools.result_store import ToolResultStore


class LoopAndSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_append_turn_transition(self) -> None:
        state = LoopState(messages=[UserMessage(content="start")])
        next_state = append_turn(
            state,
            assistant_message=AssistantMessage(blocks=[TextBlock(text="thinking")]),
            tool_results=[],
        )
        self.assertEqual(next_state.turn_count, 2)
        self.assertEqual(next_state.messages[-1].type, "assistant")

    async def test_agent_loop_and_session_engine(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = AppConfig.from_root(root, session_id="session-1", profile_dir=root / ".profile")
            memory_store = MemoryStore(config.memory_dir)
            memory_store.save_entry(
                kind="project",
                name="file-creation-style",
                description="When creating files, prefer concise code",
                content="When creating files, prefer concise code.",
            )

            registry = ToolRegistry()
            registry.register(WriteFileTool())
            executor = ToolExecutor(registry, ToolResultStore(config.tool_results_dir))
            model = ReplayModelAdapter(
                [
                    GenerationResponse(
                        assistant_blocks=[
                            ToolUseBlock(
                                name="write_file",
                                input={"path": "out.txt", "content": "done"},
                                tool_use_id="call-1",
                            )
                        ]
                    ),
                    GenerationResponse(assistant_blocks=[TextBlock(text="All done")]),
                ]
            )
            loop = AgentLoop(
                model=model,
                prompt_builder=PromptBuilder(),
                tool_executor=executor,
                tool_context=ToolContext(cwd=root),
                memory_manager=MemoryManager(memory_store),
                max_turns=4,
                token_budget=TokenBudget(total_tokens=1000),
            )
            engine = SessionEngine(
                config=config,
                agent_loop=loop,
                transcript_store=TranscriptStore(config.transcripts_dir),
            )

            state = await engine.submit("Create the file")
            self.assertEqual(state.transition_reason, "completed")
            self.assertTrue((root / "out.txt").exists())
            self.assertEqual((root / "out.txt").read_text(encoding="utf-8"), "done")
            self.assertEqual([spec.name for spec in model.requests[0].tools], ["write_file"])
            self.assertIn("Working directory", model.requests[0].system_prompt)
            self.assertIn("[workspace/workspace] file-creation-style", model.requests[0].system_prompt)
            self.assertIn("Freshness: today", model.requests[0].system_prompt)

            resumed = engine.resume()
            self.assertGreaterEqual(len(resumed), 3)

    async def test_agent_loop_consumes_stream_events_and_continues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry = ToolRegistry()
            registry.register(WriteFileTool())
            executor = ToolExecutor(registry, ToolResultStore(root / "tool-results"))
            model = ReplayModelAdapter(
                [
                    [
                        AssistantMessageStartEvent(),
                        AssistantDeltaEvent(delta="Check"),
                        AssistantDeltaEvent(delta="ing now."),
                        AssistantToolUseEvent(
                            name="write_file",
                            input={"path": "stream.txt", "content": "from-stream"},
                            tool_use_id="call-1",
                        ),
                        AssistantMessageStopEvent(stop_reason="tool_calls"),
                    ],
                    [
                        AssistantMessageStartEvent(),
                        AssistantDeltaEvent(delta="Done"),
                        AssistantMessageStopEvent(stop_reason="stop"),
                    ],
                ]
            )
            skill = Skill(
                name="planning",
                description="Plan tool use",
                body="Use tools carefully",
                paths=["src/*.py"],
                hooks={"pre_tool": ["Double check {tool_name} before running it"]},
            )
            loop = AgentLoop(
                model=model,
                prompt_builder=PromptBuilder(),
                tool_executor=executor,
                tool_context=ToolContext(cwd=root),
                skills=[skill],
                max_turns=4,
                token_budget=TokenBudget(total_tokens=1000),
            )

            state = await loop.run([UserMessage(content="Create the file")], touched_paths=("src/app.py",))
            self.assertEqual(state.transition_reason, "completed")
            self.assertEqual(state.messages[-1].type, "assistant")
            self.assertTrue((root / "stream.txt").exists())
            assistant_messages = [message for message in state.messages if message.type == "assistant"]
            progress_messages = [message for message in state.messages if message.type == "progress"]
            self.assertEqual(assistant_messages[0].text, "Checking now.")
            self.assertEqual(assistant_messages[0].tool_uses[0].name, "write_file")
            self.assertEqual(assistant_messages[-1].text, "Done")
            self.assertGreaterEqual(len(progress_messages), 2)
            self.assertEqual(progress_messages[0].stage, "tool_started")
            self.assertIn("Double check write_file", progress_messages[1].content)

    async def test_agent_loop_reactively_compacts_after_prompt_overflow(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            model = ReplayModelAdapter(
                [
                    GenerationResponse(
                        assistant_blocks=[TextBlock(text="prompt too long")],
                        stop_reason="error",
                        is_error=True,
                    ),
                    GenerationResponse(assistant_blocks=[TextBlock(text="Recovered")]),
                ]
            )
            loop = AgentLoop(
                model=model,
                prompt_builder=PromptBuilder(),
                tool_executor=ToolExecutor(ToolRegistry(), ToolResultStore(root / "tool-results")),
                tool_context=ToolContext(cwd=root),
                max_turns=3,
                compaction_limit=10,
                token_budget=TokenBudget(total_tokens=1000),
            )
            state = await loop.run([UserMessage(content=f"message-{i}") for i in range(16)])
            self.assertTrue(state.reactive_compaction_attempted)
            self.assertEqual(state.transition_reason, "completed")
            self.assertEqual(len(model.requests), 2)
            self.assertGreater(len(model.requests[0].messages), len(model.requests[1].messages))
            self.assertEqual(getattr(model.requests[1].messages[0], "kind", ""), "compaction_boundary")


if __name__ == "__main__":
    unittest.main()
