from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

from unified_assist.memory.store import MemoryEntry
from unified_assist.prompt.builder import PromptBuilder
from unified_assist.prompt.sections import PromptSection, order_sections
from unified_assist.skills.models import Skill


class PromptTests(unittest.TestCase):
    def test_order_sections_filters_and_sorts(self) -> None:
        sections = [
            PromptSection("B", "b", priority=20),
            PromptSection("A", "a", priority=10),
            PromptSection("Disabled", "x", enabled=False),
            PromptSection("Empty", "   "),
        ]
        ordered = order_sections(sections)
        self.assertEqual([section.name for section in ordered], ["A", "B"])

    def test_builder_renders_structured_prompt(self) -> None:
        builder = PromptBuilder()
        skill = Skill(
            name="planning",
            description="Plan work",
            body="Use plans",
            when_to_use="When the task is ambiguous",
            allowed_tools=["think", "read_file"],
        )
        memory = MemoryEntry(
            kind="project",
            name="deadline",
            description="Release is soon",
            content="Release is soon",
            path=Path("/tmp/deadline.md"),
            updated_at=datetime.now(timezone.utc),
        )
        prompt = builder.build(
            builder.default_sections(
                env_info="cwd=/repo",
                active_skills=[skill],
                memory_instruction="remember durable facts",
                recalled_memories=[memory],
                output_style="concise",
            )
        )
        self.assertIn("## Core Role", prompt)
        self.assertIn("### planning", prompt)
        self.assertIn("When to use: When the task is ambiguous", prompt)
        self.assertIn("Allowed tools: think, read_file", prompt)
        self.assertIn("## Skill Tool Guidance", prompt)
        self.assertIn("[workspace/workspace] deadline", prompt)
        self.assertIn("Freshness: today", prompt)
        self.assertIn("Provenance: /tmp/deadline.md", prompt)
        self.assertIn("concise", prompt)


if __name__ == "__main__":
    unittest.main()
