from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_assist.skills.hooks import HookOutcome, SkillHookRegistry, build_skill_hook_registry
from unified_assist.skills.loader import load_all_skills, load_skills_dir
from unified_assist.skills.bundled import load_bundled_skills
from unified_assist.skills.models import Skill
from unified_assist.tools.base import ToolCall, ToolContext
from unified_assist.skills.resolver import resolve_active_skills


class SkillTests(unittest.TestCase):
    def test_skill_matching_and_resolution(self) -> None:
        skill = Skill(name="frontend", description="UI work", body="Body", paths=["src/**/*.ts", "src/*.ts"])
        self.assertTrue(skill.matches_path("src/app.ts"))
        resolved = resolve_active_skills([skill], ["src/app.ts"])
        self.assertEqual([item.name for item in resolved], ["frontend"])

    def test_loader_reads_skill_frontmatter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / "planning"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: planning\ndescription: Break work down\nallowed_tools:\n  - think\npaths:\n  - src/**\n---\nUse plans\n",
                encoding="utf-8",
            )
            loaded = load_skills_dir(tmp)
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0].name, "planning")
            self.assertEqual(loaded[0].allowed_tools, ["think"])

    def test_bundled_skills_load_but_do_not_auto_activate(self) -> None:
        bundled = load_bundled_skills()
        names = {skill.name for skill in bundled}
        self.assertIn("simplify", names)
        self.assertIn("verify", names)
        self.assertEqual(resolve_active_skills(bundled, []), [])
        activated = resolve_active_skills(bundled, [], invoked_skill_names=["simplify"])
        self.assertEqual([skill.name for skill in activated], ["simplify"])

    def test_load_all_skills_prefers_workspace_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skill_dir = Path(tmp) / "simplify"
            skill_dir.mkdir()
            (skill_dir / "SKILL.md").write_text(
                "---\nname: simplify\ndescription: Local override\n---\nUse the repo-specific simplify skill\n",
                encoding="utf-8",
            )
            loaded = load_all_skills(tmp)
            loaded_by_name = {skill.name: skill for skill in loaded}
            self.assertIn("verify", loaded_by_name)
            self.assertEqual(loaded_by_name["simplify"].description, "Local override")

    def test_hook_registry(self) -> None:
        registry = SkillHookRegistry()
        seen: list[str] = []
        registry.register("session_start", "planning", lambda payload: seen.append(payload["x"]))
        outputs = registry.run("session_start", {"x": "ok"})
        self.assertEqual(seen, ["ok"])
        self.assertEqual(outputs, [None])
        self.assertEqual(registry.registered_for("session_start"), ["planning"])

    def test_build_skill_hook_registry_from_declared_hooks(self) -> None:
        skill = Skill(
            name="planning",
            description="Plan carefully",
            body="Use plans",
            hooks={
                "pre_tool": [
                    "Think before using {tool_name}",
                    {"message": "Remember context", "metadata_updates": {"hook_active": True}},
                ]
            },
        )
        registry = build_skill_hook_registry([skill])
        outputs = registry.run(
            "pre_tool",
            {
                "call": ToolCall(name="read_file", input={"path": "x"}, tool_use_id="1"),
                "context": ToolContext(cwd=Path.cwd()),
            },
        )
        self.assertIsInstance(outputs[0], HookOutcome)
        self.assertEqual(outputs[0].message, "Think before using read_file")
        self.assertEqual(outputs[1].metadata_updates["hook_active"], True)


if __name__ == "__main__":
    unittest.main()
