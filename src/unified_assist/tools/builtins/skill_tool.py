from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from unified_assist.runtime.services import RuntimeServices
from unified_assist.skills.models import Skill
from unified_assist.tools.base import BaseTool, ToolContext, ToolResult


@dataclass(slots=True)
class SkillToolInput:
    action: str
    skill: str | None = None
    query: str | None = None
    arguments: str = ""


class SkillTool(BaseTool[SkillToolInput]):
    name = "Skill"
    description = "List, search, or invoke bundled and local skills"

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["get", "list", "search"],
                },
                "skill": {"type": "string"},
                "query": {"type": "string"},
                "arguments": {"type": "string"},
                "args": {"type": "string"},
                "mode": {"type": "string"},
            },
            "required": [],
            "additionalProperties": False,
        }

    def parse_input(self, raw_input: Mapping[str, Any]) -> SkillToolInput:
        action = raw_input.get("action", raw_input.get("mode", "get"))
        skill = raw_input.get("skill")
        query = raw_input.get("query")
        arguments = raw_input.get("arguments", raw_input.get("args", ""))
        if not isinstance(action, str) or action not in {"get", "list", "search"}:
            raise ValueError("action must be get, list, or search")
        if skill is not None and not isinstance(skill, str):
            raise ValueError("skill must be a string")
        if query is not None and not isinstance(query, str):
            raise ValueError("query must be a string")
        if not isinstance(arguments, str):
            raise ValueError("arguments must be a string")
        if action != "list" and not ((skill and skill.strip()) or (query and query.strip())):
            raise ValueError("skill or query is required for get/search")
        return SkillToolInput(
            action=action,
            skill=skill.strip() if isinstance(skill, str) and skill.strip() else None,
            query=query.strip() if isinstance(query, str) and query.strip() else None,
            arguments=arguments.strip(),
        )

    def is_read_only(self, parsed_input: SkillToolInput) -> bool:
        return True

    def is_concurrency_safe(self, parsed_input: SkillToolInput) -> bool:
        return True

    async def call(self, parsed_input: SkillToolInput, context: ToolContext) -> ToolResult:
        catalog = self._catalog(context)
        if not catalog:
            return ToolResult(content="no skills available", is_error=True)

        if parsed_input.action == "list":
            lines = [f"{skill.name}: {skill.description}" for skill in sorted(catalog.values(), key=lambda item: item.name.lower())]
            return ToolResult(content="\n".join(lines))

        if parsed_input.action == "search":
            query = (parsed_input.query or parsed_input.skill or "").lower()
            matches = [
                skill
                for skill in catalog.values()
                if query in skill.name.lower()
                or query in skill.description.lower()
                or query in skill.when_to_use.lower()
            ]
            lines = [f"{skill.name}: {skill.description}" for skill in sorted(matches, key=lambda item: item.name.lower())]
            return ToolResult(content="\n".join(lines))

        skill_name = parsed_input.skill or parsed_input.query or ""
        skill = catalog.get(skill_name)
        if skill is None:
            suggestions = [
                item.name
                for item in sorted(catalog.values(), key=lambda candidate: candidate.name.lower())
                if skill_name.lower() in item.name.lower()
            ]
            message = f"unknown skill: {skill_name}"
            if suggestions:
                message += f". Did you mean: {', '.join(suggestions[:5])}?"
            return ToolResult(content=message, is_error=True)
        invoked = self._invoked_skills(context)
        invoked.add(skill.name)
        return ToolResult(
            content=self._render_skill(skill, parsed_input.arguments),
            metadata={
                "context_patch": {"invoked_skills": sorted(invoked)},
                "skill_name": skill.name,
            },
        )

    def _catalog(self, context: ToolContext) -> dict[str, Skill]:
        raw = context.metadata.get("skill_catalog")
        if isinstance(raw, dict) and all(isinstance(item, Skill) for item in raw.values()):
            return {name: skill for name, skill in raw.items() if isinstance(name, str)}
        services = context.metadata.get("runtime_services")
        if isinstance(services, RuntimeServices):
            return {skill.name: skill for skill in services.skills}
        return {}

    def _invoked_skills(self, context: ToolContext) -> set[str]:
        raw = context.metadata.get("invoked_skills", [])
        if not isinstance(raw, list):
            return set()
        return {str(name) for name in raw if str(name).strip()}

    def _render_skill(self, skill: Skill, arguments: str) -> str:
        lines = [
            f"# Skill: {skill.name}",
            f"Description: {skill.description}",
        ]
        if skill.when_to_use:
            lines.append(f"When to use: {skill.when_to_use}")
        if skill.allowed_tools:
            lines.append(f"Preferred tools: {', '.join(skill.allowed_tools)}")
        lines.append(f"Context: {skill.context}")
        if arguments:
            lines.append(f"Requested arguments: {arguments}")
        lines.extend(["", skill.body.strip()])
        return "\n".join(lines).strip()
