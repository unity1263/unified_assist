from __future__ import annotations

from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class Skill:
    name: str
    description: str
    body: str
    when_to_use: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    context: str = "inline"
    paths: list[str] = field(default_factory=list)
    root_dir: Path | None = None
    hooks: dict[str, list[str]] = field(default_factory=dict)
    auto_activate: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def matches_path(self, path: str) -> bool:
        if not self.paths:
            return True
        return any(fnmatch(path, pattern) for pattern in self.paths)
