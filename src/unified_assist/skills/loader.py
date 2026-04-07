from __future__ import annotations

from pathlib import Path

from unified_assist.skills.bundled import load_bundled_skills
from unified_assist.skills.models import Skill
from unified_assist.utils.yaml_frontmatter import parse_frontmatter


def _derive_description(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return "Skill"


def load_skills_dir(base_dir: str | Path) -> list[Skill]:
    root = Path(base_dir)
    if not root.exists():
        return []

    skills: list[Skill] = []
    for child in sorted(root.iterdir()):
        skill_file = child / "SKILL.md"
        if not child.is_dir() or not skill_file.exists():
            continue
        raw = skill_file.read_text(encoding="utf-8")
        metadata, body = parse_frontmatter(raw)
        name = str(metadata.get("name", child.name))
        description = str(metadata.get("description", _derive_description(body)))
        allowed_tools = metadata.get("allowed_tools", []) or []
        paths = metadata.get("paths", []) or []
        hooks = metadata.get("hooks", {}) or {}
        skills.append(
            Skill(
                name=name,
                description=description,
                body=body.strip(),
                when_to_use=str(metadata.get("when_to_use", "")),
                allowed_tools=list(allowed_tools),
                context=str(metadata.get("context", "inline")),
                paths=list(paths),
                root_dir=child,
                hooks=dict(hooks),
                auto_activate=bool(metadata.get("auto_activate", True)),
                metadata=metadata,
            )
        )
    return skills


def merge_skills(*skill_groups: list[Skill]) -> list[Skill]:
    merged: dict[str, Skill] = {}
    for group in skill_groups:
        for skill in group:
            merged[skill.name] = skill
    return list(merged.values())


def load_all_skills(base_dir: str | Path) -> list[Skill]:
    return merge_skills(load_bundled_skills(), load_skills_dir(base_dir))
