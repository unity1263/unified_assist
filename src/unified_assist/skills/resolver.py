from __future__ import annotations

from collections.abc import Iterable

from unified_assist.skills.models import Skill


def resolve_active_skills(
    skills: Iterable[Skill],
    touched_paths: Iterable[str] = (),
    invoked_skill_names: Iterable[str] = (),
) -> list[Skill]:
    touched = list(touched_paths)
    invoked = set(invoked_skill_names)
    resolved: list[Skill] = []
    seen: set[str] = set()
    for skill in skills:
        active = skill.name in invoked or (
            skill.auto_activate and (not skill.paths or any(skill.matches_path(path) for path in touched))
        )
        if active and skill.name not in seen:
            resolved.append(skill)
            seen.add(skill.name)
    return resolved
