from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from unified_assist.utils.paths import ensure_dir


@dataclass(slots=True)
class AppConfig:
    root_dir: Path
    session_id: str = "default"

    @classmethod
    def from_root(cls, root_dir: str | Path, session_id: str = "default") -> "AppConfig":
        return cls(root_dir=Path(root_dir).resolve(), session_id=session_id)

    @property
    def data_dir(self) -> Path:
        return self.root_dir / ".assist"

    @property
    def memory_dir(self) -> Path:
        return self.data_dir / "memory"

    @property
    def skills_dir(self) -> Path:
        return self.root_dir / "skills"

    @property
    def transcripts_dir(self) -> Path:
        return self.data_dir / "transcripts"

    @property
    def tool_results_dir(self) -> Path:
        return self.data_dir / "tool_results"

    @property
    def session_memory_dir(self) -> Path:
        return self.data_dir / "session_memory"

    @property
    def session_memory_path(self) -> Path:
        return self.session_memory_dir / "notes.md"

    def ensure_directories(self) -> None:
        ensure_dir(self.data_dir)
        ensure_dir(self.memory_dir)
        ensure_dir(self.skills_dir)
        ensure_dir(self.transcripts_dir)
        ensure_dir(self.tool_results_dir)
        ensure_dir(self.session_memory_dir)
