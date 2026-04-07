from __future__ import annotations

from typing import Iterable

from unified_assist.memory.freshness import freshness_note, freshness_text
from unified_assist.memory.recall import RecalledMemory
from unified_assist.memory.types import MemoryFact
from unified_assist.prompt.sections import PromptSection, order_sections
from unified_assist.skills.models import Skill
from unified_assist.memory.store import MemoryEntry


DEFAULT_ROLE = (
    "You are Unified Claw, a disciplined coding assistant. "
    "Use tools deliberately, ground claims in observed state, and keep working until the task is complete."
)

DEFAULT_RULES = (
    "Treat the model as the planner, not the executor. "
    "Prefer tool-backed facts, preserve user intent, and keep outputs concise and useful."
)


class PromptBuilder:
    def __init__(self, base_role: str = DEFAULT_ROLE, operating_rules: str = DEFAULT_RULES) -> None:
        self.base_role = base_role
        self.operating_rules = operating_rules

    def default_sections(
        self,
        *,
        env_info: str = "",
        active_skills: list[Skill] | None = None,
        memory_instruction: str = "",
        recalled_memories: list[MemoryEntry | MemoryFact | RecalledMemory] | None = None,
        session_guidance: str = "",
        output_style: str = "",
    ) -> list[PromptSection]:
        active_skills = active_skills or []
        recalled_memories = recalled_memories or []

        skill_text = self.render_active_skills(active_skills)
        skill_tool_guidance = self.render_skill_tool_guidance(active_skills)
        memory_text = self.render_recalled_memories(recalled_memories)

        return [
            PromptSection("Core Role", self.base_role, priority=10),
            PromptSection("Operating Rules", self.operating_rules, priority=20),
            PromptSection("Environment Info", env_info, priority=30, enabled=bool(env_info)),
            PromptSection("Active Skills", skill_text, priority=40, enabled=bool(skill_text)),
            PromptSection(
                "Skill Tool Guidance",
                skill_tool_guidance,
                priority=45,
                enabled=bool(skill_tool_guidance),
            ),
            PromptSection(
                "Memory Instructions",
                memory_instruction,
                priority=50,
                enabled=bool(memory_instruction),
            ),
            PromptSection(
                "Recalled Memories",
                memory_text,
                priority=60,
                enabled=bool(memory_text),
            ),
            PromptSection(
                "Session Guidance",
                session_guidance,
                priority=70,
                enabled=bool(session_guidance),
            ),
            PromptSection("Output Style", output_style, priority=80, enabled=bool(output_style)),
        ]

    def build(self, sections: list[PromptSection]) -> str:
        ordered = order_sections(sections)
        chunks: list[str] = []
        for section in ordered:
            chunks.append(f"## {section.name}\n{section.content.strip()}")
        return "\n\n".join(chunks).strip()

    def render_active_skills(self, active_skills: Iterable[Skill]) -> str:
        chunks: list[str] = []
        for skill in active_skills:
            lines = [f"### {skill.name}", f"Description: {skill.description}"]
            if skill.when_to_use:
                lines.append(f"When to use: {skill.when_to_use}")
            if skill.allowed_tools:
                lines.append(f"Allowed tools: {', '.join(skill.allowed_tools)}")
            lines.append(f"Context mode: {skill.context}")
            if skill.body:
                lines.append("Instructions:")
                lines.append(skill.body.strip())
            chunks.append("\n".join(lines).strip())
        return "\n\n".join(chunks).strip()

    def render_skill_tool_guidance(self, active_skills: Iterable[Skill]) -> str:
        lines: list[str] = []
        for skill in active_skills:
            if skill.allowed_tools:
                lines.append(f"- {skill.name}: prefer {', '.join(skill.allowed_tools)} when applying this skill")
        if not lines:
            return ""
        return (
            "When an active skill declares allowed tools, treat that list as the preferred toolset for work governed by that skill.\n"
            + "\n".join(lines)
        )

    def render_recalled_memories(
        self, recalled_memories: Iterable[MemoryEntry | MemoryFact | RecalledMemory]
    ) -> str:
        chunks: list[str] = []
        for item in recalled_memories:
            recalled = self._normalize_memory(item)
            lines = [
                f"- [{recalled.entry.scope}/{recalled.entry.memory_type}] {recalled.entry.name}",
                f"  Summary: {recalled.entry.description or recalled.excerpt}",
                f"  Freshness: {recalled.freshness}",
                f"  Provenance: {recalled.provenance}",
                f"  Detail: {recalled.excerpt}",
            ]
            verification = recalled.verification_note or recalled.freshness_note
            if verification:
                lines.append(f"  Verification: {verification}")
            chunks.append("\n".join(lines))
        return "\n\n".join(chunks).strip()

    def _normalize_memory(self, item: MemoryEntry | MemoryFact | RecalledMemory) -> RecalledMemory:
        if isinstance(item, RecalledMemory):
            return item
        if isinstance(item, MemoryFact):
            content = item.content.strip() or item.description.strip() or item.name
            excerpt = content if len(content) <= 220 else content[:217].rstrip() + "..."
            freshness = freshness_text(item.updated_at)
            note = freshness_note(item.updated_at)
            verification = note
            if item.sensitivity == "secret":
                excerpt = f"Secret memory exists for '{item.name}'. Ask the user before using exact details."
                verification = "Do not reveal the secret verbatim without the user's consent."
            return RecalledMemory(
                fact=item,
                score=0.0,
                excerpt=excerpt,
                freshness=freshness,
                freshness_note=note,
                provenance=item.source_ref or str(item.path or "memory"),
                verification_note=verification,
            )
        content = item.content.strip() or item.description.strip() or item.name
        excerpt = content if len(content) <= 220 else content[:217].rstrip() + "..."
        return RecalledMemory(
            fact=MemoryFact(
                fact_id=str(item.path),
                title=item.name,
                summary=item.description,
                detail=item.content,
                memory_type=item.kind if item.kind != "project" else "workspace",
                scope="workspace" if item.kind in {"project", "reference"} else "private",
                sensitivity="normal",
                confidence=0.5,
                observed_at=item.updated_at,
                last_verified_at=item.updated_at,
                expires_at=None,
                source_ref=str(item.path),
                entity_refs=(),
                status="active",
                export_path=item.path,
            ),
            score=0.0,
            excerpt=excerpt,
            freshness=freshness_text(item.updated_at),
            freshness_note=freshness_note(item.updated_at),
            provenance=str(item.path),
            verification_note=freshness_note(item.updated_at),
        )
