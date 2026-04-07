from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from unified_assist.app.app_config import AppConfig
from unified_assist.memory.freshness import freshness_note, freshness_text
from unified_assist.memory.manager import MemoryManager
from unified_assist.memory.recall import RecalledMemory
from unified_assist.memory.store import MemoryStore
from unified_assist.memory.types import MemoryFact, MemoryObservation, RecallContext, utc_now
from unified_assist.messages.models import UserMessage


class MemoryTests(unittest.TestCase):
    def test_freshness_helpers(self) -> None:
        now = datetime.now(timezone.utc)
        old = now - timedelta(days=3)
        self.assertEqual(freshness_text(old, now=now), "3 days old")
        self.assertIn("3 days old", freshness_note(old, now=now))

    def test_prepare_imports_legacy_markdown_and_builds_digests(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = AppConfig.from_root(root, session_id="s1", profile_dir=root / ".profile")
            legacy = MemoryStore(config.memory_dir)
            legacy.save_entry(
                kind="project",
                name="release-window",
                description="Release next week",
                content="The workspace release is next week.",
            )
            legacy.save_entry(
                kind="feedback",
                name="status-style",
                description="Prefer concise status updates",
                content="The user prefers concise status updates.",
            )

            manager = MemoryManager.from_config(config)
            recalled = manager.recall(
                RecallContext(
                    query="release concise status",
                    active_workspace=str(root),
                ),
                limit=5,
            )

            self.assertTrue(config.workspace_memory_db.exists())
            self.assertTrue(config.profile_memory_db.exists())
            self.assertTrue((config.memory_dir / "MEMORY.md").exists())
            self.assertTrue((config.profile_memory_dir / "MEMORY.md").exists())
            self.assertTrue(any(item.entry.memory_type == "workspace" for item in recalled))
            self.assertTrue(any(item.entry.scope == "private" for item in recalled))

    def test_routing_sensitivity_and_tombstones(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = AppConfig.from_root(root, session_id="s1", profile_dir=root / ".profile")
            manager = MemoryManager.from_config(config)

            result = manager.record_observations(
                [
                    MemoryObservation(
                        title="Prefers concise replies",
                        summary="The user prefers concise replies.",
                        detail="The user prefers concise replies.",
                        memory_type="preference",
                    ),
                    MemoryObservation(
                        title="Workspace uses uv",
                        summary="This workspace uses uv for Python tasks.",
                        detail="This workspace uses uv for Python tasks.",
                        memory_type="workspace",
                    ),
                    MemoryObservation(
                        title="API token",
                        summary="Personal API token",
                        detail="The user's API token is 12345.",
                        memory_type="profile",
                        sensitivity="secret",
                    ),
                ]
            )

            self.assertEqual({fact.scope for fact in result.promoted_facts}, {"private", "workspace"})
            self.assertEqual(len(result.pending_confirmations), 1)
            self.assertEqual(result.pending_confirmations[0].scope, "private")
            self.assertEqual(result.pending_confirmations[0].status, "pending_confirmation")

            workspace_only = manager.recall(
                RecallContext(
                    query="uv token",
                    active_workspace=str(root),
                    allowed_scopes=("workspace",),
                )
            )
            self.assertTrue(all(item.entry.scope == "workspace" for item in workspace_only))
            self.assertFalse(any("12345" in item.excerpt for item in workspace_only))

            forgotten = manager.forget("Workspace uses uv", scope="workspace")
            self.assertEqual(forgotten, 1)
            manager.record_observations(
                [
                    MemoryObservation(
                        title="Workspace uses uv",
                        summary="This workspace uses uv for Python tasks.",
                        detail="This workspace uses uv for Python tasks.",
                        memory_type="workspace",
                    )
                ]
            )
            workspace_after_forget = manager.recall(
                RecallContext(
                    query="uv",
                    active_workspace=str(root),
                    allowed_scopes=("workspace",),
                )
            )
            self.assertEqual(workspace_after_forget, [])

    def test_recall_boosts_people_time_and_redacts_secret_facts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = AppConfig.from_root(root, session_id="s1", profile_dir=root / ".profile")
            manager = MemoryManager.from_config(config)
            manager.record_observations(
                [
                    MemoryObservation(
                        title="Alice is vegetarian",
                        summary="Alice prefers vegetarian restaurants.",
                        detail="Alice prefers vegetarian restaurants.",
                        memory_type="person",
                        entity_refs=("Alice",),
                    ),
                    MemoryObservation(
                        title="Roadmap review tomorrow",
                        summary="Review roadmap.md tomorrow with Alice.",
                        detail="Review roadmap.md tomorrow with Alice.",
                        memory_type="commitment",
                        scope="workspace",
                        workspace=str(root),
                        expires_at=utc_now() + timedelta(days=1),
                        entity_refs=("Alice",),
                        metadata={"source_type": "tool_result"},
                    ),
                ]
            )
            secret = MemoryFact(
                fact_id="secret-1",
                title="Home alarm code",
                summary="Home alarm code exists.",
                detail="Alarm code is 9182.",
                memory_type="profile",
                scope="private",
                sensitivity="secret",
                confidence=0.9,
                observed_at=utc_now(),
                last_verified_at=utc_now(),
                expires_at=None,
                source_ref="manual://secret",
                entity_refs=(),
                status="active",
            )
            manager.profile_store.upsert_fact(secret)

            recalled = manager.recall(
                RecallContext(
                    query="What does Alice need tomorrow and what's the alarm reminder?",
                    active_workspace=str(root),
                    participants=("Alice",),
                    touched_paths=("roadmap.md",),
                    source_hints=("roadmap.md",),
                ),
                limit=5,
            )

            self.assertTrue(any(item.entry.title == "Roadmap review tomorrow" for item in recalled))
            self.assertTrue(any(item.entry.title == "Alice is vegetarian" for item in recalled))
            secret_memory = next(item for item in recalled if item.entry.title == "Home alarm code")
            self.assertIsInstance(secret_memory, RecalledMemory)
            self.assertIn("Ask the user before using exact details", secret_memory.excerpt)
            self.assertNotIn("9182", secret_memory.excerpt)

    def test_capture_turn_and_consolidate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = AppConfig.from_root(root, session_id="s1", profile_dir=root / ".profile")
            manager = MemoryManager.from_config(config)

            capture = manager.capture_turn(
                [UserMessage(content="Remember that I prefer concise updates.")],
                active_workspace=str(root),
                session_id="s1",
            )
            self.assertEqual(len(capture.promoted_facts), 1)
            self.assertEqual(capture.promoted_facts[0].memory_type, "preference")

            manager.record_observations(
                [
                    MemoryObservation(
                        title="Old deadline",
                        summary="The old deadline passed yesterday.",
                        detail="The old deadline passed yesterday.",
                        memory_type="commitment",
                        scope="workspace",
                        workspace=str(root),
                        expires_at=utc_now() - timedelta(days=1),
                    )
                ]
            )
            consolidated = manager.consolidate()
            self.assertEqual(consolidated["workspace"]["closed_commitments"], 1)
            self.assertTrue((config.memory_dir / "MEMORY.md").exists())


if __name__ == "__main__":
    unittest.main()
