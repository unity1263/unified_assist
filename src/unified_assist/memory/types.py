from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


MemoryType = Literal[
    "profile",
    "preference",
    "person",
    "relationship",
    "commitment",
    "event",
    "routine",
    "workspace",
    "reference",
]

MemoryScope = Literal["private", "workspace", "shared"]
SensitivityLevel = Literal["normal", "sensitive", "secret"]
MemoryStatus = Literal["active", "pending_confirmation", "closed", "archived", "deleted"]
ObservationStatus = Literal["candidate", "pending_confirmation", "recorded", "archived"]

MEMORY_TYPES: tuple[MemoryType, ...] = (
    "profile",
    "preference",
    "person",
    "relationship",
    "commitment",
    "event",
    "routine",
    "workspace",
    "reference",
)
MEMORY_SCOPES: tuple[MemoryScope, ...] = ("private", "workspace", "shared")
SENSITIVITY_LEVELS: tuple[SensitivityLevel, ...] = ("normal", "sensitive", "secret")
PRIVATE_DEFAULT_TYPES: tuple[MemoryType, ...] = (
    "profile",
    "preference",
    "person",
    "relationship",
    "routine",
)
WORKSPACE_DEFAULT_TYPES: tuple[MemoryType, ...] = ("workspace", "reference")
TIME_BOUND_TYPES: tuple[MemoryType, ...] = ("commitment", "event")


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True, slots=True)
class MemorySpace:
    scope: MemoryScope
    db_path: Path
    export_dir: Path
    workspace: str | None = None

    @property
    def name(self) -> str:
        return self.scope


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    source_type: str
    source_ref: str
    snippet: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MemoryObservation:
    title: str
    summary: str
    detail: str
    memory_type: MemoryType
    scope: MemoryScope | None = None
    sensitivity: SensitivityLevel = "normal"
    confidence: float = 0.6
    observed_at: datetime = field(default_factory=utc_now)
    last_verified_at: datetime | None = None
    expires_at: datetime | None = None
    source_ref: str = ""
    entity_refs: tuple[str, ...] = ()
    status: ObservationStatus = "candidate"
    workspace: str | None = None
    requires_confirmation: bool = False
    dedupe_key: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    evidence: tuple[EvidenceRef, ...] = ()
    observation_id: str | None = None


@dataclass(frozen=True, slots=True)
class MemoryFact:
    fact_id: str
    title: str
    summary: str
    detail: str
    memory_type: MemoryType
    scope: MemoryScope
    sensitivity: SensitivityLevel
    confidence: float
    observed_at: datetime
    last_verified_at: datetime
    expires_at: datetime | None
    source_ref: str
    entity_refs: tuple[str, ...]
    status: MemoryStatus
    workspace: str | None = None
    dedupe_key: str | None = None
    provenance: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    export_path: Path | None = None

    @property
    def name(self) -> str:
        return self.title

    @property
    def description(self) -> str:
        return self.summary

    @property
    def content(self) -> str:
        return self.detail

    @property
    def kind(self) -> str:
        return self.memory_type

    @property
    def path(self) -> Path | None:
        return self.export_path

    @property
    def updated_at(self) -> datetime:
        return self.last_verified_at


@dataclass(frozen=True, slots=True)
class RecallContext:
    query: str
    active_workspace: str | None = None
    participants: tuple[str, ...] = ()
    current_time: datetime = field(default_factory=utc_now)
    todos: tuple[str, ...] = ()
    touched_paths: tuple[str, ...] = ()
    source_hints: tuple[str, ...] = ()
    allowed_scopes: tuple[MemoryScope, ...] = ("private", "workspace")


@dataclass(frozen=True, slots=True)
class RecordObservationsResult:
    observations: tuple[MemoryObservation, ...]
    promoted_facts: tuple[MemoryFact, ...]
    pending_confirmations: tuple[MemoryObservation, ...]

