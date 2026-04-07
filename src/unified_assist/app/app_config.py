from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from unified_assist.utils.paths import ensure_dir


@dataclass(slots=True)
class AppConfig:
    root_dir: Path
    session_id: str = "default"
    profile_root: Path | None = None

    @classmethod
    def from_root(
        cls,
        root_dir: str | Path,
        session_id: str = "default",
        profile_dir: str | Path | None = None,
    ) -> "AppConfig":
        profile_root = Path(profile_dir).expanduser().resolve() if profile_dir else None
        return cls(
            root_dir=Path(root_dir).resolve(),
            session_id=session_id,
            profile_root=profile_root,
        )

    @property
    def data_dir(self) -> Path:
        return self.root_dir / ".assist"

    @property
    def memory_dir(self) -> Path:
        return self.data_dir / "memory"

    @property
    def profile_data_dir(self) -> Path:
        if self.profile_root is not None:
            return self.profile_root
        env_override = os.environ.get("UNIFIED_ASSIST_PROFILE_DIR", "").strip()
        if env_override:
            return Path(env_override).expanduser().resolve()
        return (self.data_dir / "profile").resolve()

    @property
    def profile_memory_dir(self) -> Path:
        return self.profile_data_dir / "memory"

    @property
    def profile_memory_db(self) -> Path:
        return self.profile_data_dir / "memory.sqlite3"

    @property
    def workspace_memory_db(self) -> Path:
        return self.data_dir / "memory.sqlite3"

    @property
    def skills_dir(self) -> Path:
        return self.root_dir / "skills"

    @property
    def transcripts_dir(self) -> Path:
        return self.data_dir / "transcripts"

    @property
    def tool_results_dir(self) -> Path:
        return self.data_dir / "tool_results"

    def ensure_directories(self) -> None:
        ensure_dir(self.data_dir)
        ensure_dir(self.memory_dir)
        ensure_dir(self.profile_data_dir)
        ensure_dir(self.profile_memory_dir)
        ensure_dir(self.skills_dir)
        ensure_dir(self.transcripts_dir)
        ensure_dir(self.tool_results_dir)
