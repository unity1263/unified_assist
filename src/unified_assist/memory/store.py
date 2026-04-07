from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from unified_assist.utils.paths import ensure_dir, slugify
from unified_assist.utils.yaml_frontmatter import dump_frontmatter, parse_frontmatter


MemoryKind = Literal["user", "feedback", "project", "reference"]
MEMORY_KINDS: tuple[MemoryKind, ...] = ("user", "feedback", "project", "reference")


@dataclass(slots=True)
class MemoryEntry:
    kind: MemoryKind
    name: str
    description: str
    content: str
    path: Path
    updated_at: datetime


class MemoryStore:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = Path(root_dir)

    def ensure_structure(self) -> None:
        ensure_dir(self.root_dir)
        for kind in MEMORY_KINDS:
            ensure_dir(self.root_dir / kind)
        index_path = self.root_dir / "MEMORY.md"
        if not index_path.exists():
            index_path.write_text("# Memory Index\n", encoding="utf-8")

    def save_entry(
        self,
        *,
        kind: MemoryKind,
        name: str,
        description: str,
        content: str,
        slug: str | None = None,
    ) -> MemoryEntry:
        self.ensure_structure()
        file_slug = slug or slugify(name)
        target = self.root_dir / kind / f"{file_slug}.md"
        now = datetime.now(timezone.utc)
        rendered = dump_frontmatter(
            {
                "name": name,
                "description": description,
                "type": kind,
                "updated_at": now.isoformat(),
            },
            content.strip() + "\n",
        )
        target.write_text(rendered, encoding="utf-8")
        return MemoryEntry(
            kind=kind,
            name=name,
            description=description,
            content=content.strip(),
            path=target,
            updated_at=now,
        )

    def load_entry(self, path: str | Path) -> MemoryEntry:
        target = Path(path)
        metadata, body = parse_frontmatter(target.read_text(encoding="utf-8"))
        updated_at = metadata.get("updated_at")
        if isinstance(updated_at, datetime):
            parsed_updated = (
                updated_at if updated_at.tzinfo is not None else updated_at.replace(tzinfo=timezone.utc)
            )
        elif isinstance(updated_at, str):
            parsed_updated = datetime.fromisoformat(updated_at)
        else:
            parsed_updated = datetime.fromtimestamp(target.stat().st_mtime, tz=timezone.utc)
        kind = str(metadata.get("type", target.parent.name))
        if kind not in MEMORY_KINDS:
            raise ValueError(f"invalid memory kind: {kind}")
        return MemoryEntry(
            kind=kind,  # type: ignore[arg-type]
            name=str(metadata.get("name", target.stem)),
            description=str(metadata.get("description", "")),
            content=body.strip(),
            path=target,
            updated_at=parsed_updated,
        )

    def list_entries(self, kind: MemoryKind | None = None) -> list[MemoryEntry]:
        self.ensure_structure()
        roots = [self.root_dir / kind] if kind else [self.root_dir / item for item in MEMORY_KINDS]
        entries: list[MemoryEntry] = []
        for root in roots:
            if not root.exists():
                continue
            for path in sorted(root.glob("*.md")):
                entries.append(self.load_entry(path))
        return sorted(entries, key=lambda entry: entry.updated_at, reverse=True)
