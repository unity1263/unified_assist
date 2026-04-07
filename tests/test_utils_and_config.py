from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from unified_assist.app.app_config import AppConfig
from unified_assist.utils.paths import ensure_dir, slugify
from unified_assist.utils.yaml_frontmatter import dump_frontmatter, parse_frontmatter


class UtilsAndConfigTests(unittest.TestCase):
    def test_slugify_and_ensure_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = ensure_dir(Path(tmp) / "a" / "b")
            self.assertTrue(target.exists())
            self.assertEqual(slugify("Hello, World!"), "hello-world")

    def test_frontmatter_roundtrip(self) -> None:
        rendered = dump_frontmatter({"name": "skill", "paths": ["src/**"]}, "Body text\n")
        metadata, body = parse_frontmatter(rendered)
        self.assertEqual(metadata["name"], "skill")
        self.assertEqual(metadata["paths"], ["src/**"])
        self.assertEqual(body.strip(), "Body text")

    def test_app_config_creates_expected_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = AppConfig.from_root(tmp, session_id="s1", profile_dir=Path(tmp) / ".profile")
            config.ensure_directories()
            self.assertTrue(config.data_dir.exists())
            self.assertTrue(config.memory_dir.exists())
            self.assertTrue(config.profile_data_dir.exists())
            self.assertTrue(config.profile_memory_dir.exists())
            self.assertTrue(config.profile_memory_db.parent.exists())
            self.assertTrue(config.workspace_memory_db.parent.exists())
            self.assertTrue(config.skills_dir.exists())
            self.assertTrue(config.transcripts_dir.exists())
            self.assertTrue(config.tool_results_dir.exists())


if __name__ == "__main__":
    unittest.main()
