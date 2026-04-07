from __future__ import annotations

from dataclasses import dataclass, field
from collections import defaultdict
from collections.abc import Callable
from typing import Any

from unified_assist.skills.models import Skill


Hook = Callable[[dict[str, Any]], Any]


@dataclass(frozen=True, slots=True)
class HookOutcome:
    message: str = ""
    metadata_updates: dict[str, Any] = field(default_factory=dict)
    stage: str | None = None
    source: str = "hook"


class SkillHookRegistry:
    def __init__(self) -> None:
        self._hooks: dict[str, list[tuple[str, Hook]]] = defaultdict(list)

    def register(self, event: str, skill_name: str, hook: Hook) -> None:
        self._hooks[event].append((skill_name, hook))

    def run(self, event: str, payload: dict[str, Any]) -> list[Any]:
        return [hook(payload) for _, hook in self._hooks.get(event, [])]

    def registered_for(self, event: str) -> list[str]:
        return [skill_name for skill_name, _ in self._hooks.get(event, [])]


def build_skill_hook_registry(skills: list[Skill]) -> SkillHookRegistry:
    registry = SkillHookRegistry()
    for skill in skills:
        for event, hooks in skill.hooks.items():
            if not isinstance(hooks, list):
                continue
            for item in hooks:
                outcome = _normalize_declared_hook(skill.name, event, item)
                if outcome is None:
                    continue
                registry.register(
                    event,
                    skill.name,
                    lambda payload, outcome=outcome: _render_hook_outcome(outcome, payload),
                )
    return registry


def _normalize_declared_hook(skill_name: str, event: str, item: Any) -> HookOutcome | None:
    if isinstance(item, str):
        message = item.strip()
        if not message:
            return None
        return HookOutcome(message=message, stage=event, source=f"skill:{skill_name}")
    if isinstance(item, dict):
        message = str(item.get("message", "")).strip()
        metadata_updates = item.get("metadata_updates", {}) or {}
        if not isinstance(metadata_updates, dict):
            metadata_updates = {}
        if not message and not metadata_updates:
            return None
        return HookOutcome(
            message=message,
            metadata_updates=dict(metadata_updates),
            stage=str(item.get("stage", event)),
            source=f"skill:{skill_name}",
        )
    return None


def _render_hook_outcome(outcome: HookOutcome, payload: dict[str, Any]) -> HookOutcome:
    call = payload.get("call")
    call_name = getattr(call, "name", "")
    message = outcome.message.replace("{tool_name}", call_name) if call_name else outcome.message
    return HookOutcome(
        message=message,
        metadata_updates=dict(outcome.metadata_updates),
        stage=outcome.stage,
        source=outcome.source,
    )
