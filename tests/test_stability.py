from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_assist.messages.blocks import TextBlock, ToolResultBlock, ToolUseBlock
from unified_assist.messages.models import AssistantMessage, SystemMessage, ToolResultMessage, UserMessage
from unified_assist.stability.compaction import compact_messages
from unified_assist.stability.query_guard import QueryGuard
from unified_assist.stability.recovery import maybe_recover
from unified_assist.stability.resume import repair_messages
from unified_assist.stability.token_budget import TokenBudget
from unified_assist.stability.transcript_store import TranscriptStore


class StabilityTests(unittest.TestCase):
    def test_query_guard(self) -> None:
        guard = QueryGuard()
        self.assertTrue(guard.reserve())
        guard.cancel_reservation()
        generation = guard.try_start()
        self.assertIsNotNone(generation)
        self.assertTrue(guard.is_active)
        self.assertTrue(guard.end(generation or 0))
        self.assertFalse(guard.is_active)

    def test_transcript_store_and_resume_repair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = TranscriptStore(tmp)
            session_id = "s1"
            reservation_id = store.reserve_turn(session_id, UserMessage(content="hello"))
            loaded = store.load_transcript(session_id)
            self.assertEqual(len(loaded.messages), 0)
            self.assertEqual(len(loaded.pending_turns), 1)
            repaired_pending = repair_messages(loaded.messages, pending_turns=loaded.pending_turns)
            self.assertEqual(repaired_pending[0].content, "hello")
            self.assertIsInstance(repaired_pending[1], SystemMessage)
            self.assertTrue(isinstance(repaired_pending[-1], UserMessage) and repaired_pending[-1].is_meta)

            store.commit_turn(
                session_id,
                reservation_id,
                [AssistantMessage(blocks=[TextBlock(text="done")])],
            )
            committed = store.load_messages(session_id)
            self.assertEqual(len(committed), 2)
            self.assertEqual(committed[0].content, "hello")

            assistant = AssistantMessage(
                blocks=[ToolUseBlock(name="write_file", input={"path": "a"}, tool_use_id="call-1")]
            )
            resolved = repair_messages(
                [
                    UserMessage(content="hello"),
                    assistant,
                    ToolResultMessage(results=[ToolResultBlock(tool_use_id="call-1", content="done")]),
                ]
            )
            self.assertEqual(len(resolved), 3)

            unresolved = repair_messages([UserMessage(content="hello"), assistant])
            self.assertEqual(unresolved[0].content, "hello")
            self.assertIsInstance(unresolved[1], SystemMessage)
            self.assertIn("interrupted", unresolved[1].content.lower())
            self.assertTrue(isinstance(unresolved[-1], UserMessage) and unresolved[-1].is_meta)

    def test_compaction_recovery_and_budget(self) -> None:
        compacted = compact_messages([UserMessage(content=f"msg-{i}") for i in range(20)], max_messages=5, preserve_tail=2)
        self.assertEqual(compacted[0].type, "attachment")
        self.assertEqual(compacted[0].kind, "compaction_boundary")
        self.assertEqual(compacted[1].type, "system")

        recovery = maybe_recover(
            AssistantMessage(blocks=[TextBlock(text="max_output_tokens reached")], is_error=True),
            recovery_count=0,
        )
        self.assertTrue(recovery.should_retry)

        prompt_overflow = maybe_recover(
            AssistantMessage(blocks=[TextBlock(text="prompt too long")], is_error=True),
            recovery_count=0,
        )
        self.assertTrue(prompt_overflow.should_retry)
        self.assertTrue(prompt_overflow.should_compact)

        budget = TokenBudget(total_tokens=10, continue_ratio=0.5)
        decision = budget.decide([UserMessage(content="x" * 30)])
        self.assertIn(decision.action, {"continue", "stop"})


if __name__ == "__main__":
    unittest.main()
