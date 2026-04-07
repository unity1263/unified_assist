from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from unified_assist.memory.extractor import MemoryExtractor
from unified_assist.memory.recall import RecalledMemory, recall_facts
from unified_assist.memory.sqlite_store import SQLiteMemoryStore, dedupe_key_for
from unified_assist.memory.store import MemoryEntry, MemoryStore
from unified_assist.memory.types import (
    EvidenceRef,
    MemoryFact,
    MemoryObservation,
    MemorySpace,
    MemoryScope,
    MemoryType,
    PRIVATE_DEFAULT_TYPES,
    RecallContext,
    RecordObservationsResult,
    WORKSPACE_DEFAULT_TYPES,
)

if TYPE_CHECKING:
    from unified_assist.app.app_config import AppConfig


LEGACY_KIND_TO_TYPE: dict[str, MemoryType] = {
    "user": "profile",
    "feedback": "preference",
    "project": "workspace",
    "reference": "reference",
}

MEMORY_INSTRUCTIONS = (
    "Use memory as audited, scope-aware assistant context. "
    "Private memory is for personal preferences, people, routines, and sensitive user facts. "
    "Workspace memory is for active workspace policies, references, and shared commitments. "
    "Treat memory as point-in-time evidence with provenance and freshness, and verify stale items before relying on them. "
    "Secret memories must never be quoted verbatim without the user's consent."
)


class MemoryManager:
    def __init__(
        self,
        store: MemoryStore | None = None,
        *,
        profile_store: SQLiteMemoryStore | None = None,
        workspace_store: SQLiteMemoryStore | None = None,
        legacy_store: MemoryStore | None = None,
        workspace_id: str | None = None,
        extractor: MemoryExtractor | None = None,
    ) -> None:
        derived_workspace = workspace_id
        derived_legacy = legacy_store or store
        if store is not None and (profile_store is None or workspace_store is None):
            root = Path(store.root_dir)
            guessed_workspace = workspace_id
            if guessed_workspace is None:
                guessed_workspace = str(root.parent.parent if root.name == "memory" else root.parent)
            profile_store = SQLiteMemoryStore(
                MemorySpace(
                    scope="private",
                    db_path=root / "private-memory.sqlite3",
                    export_dir=root / "private",
                )
            )
            workspace_store = SQLiteMemoryStore(
                MemorySpace(
                    scope="workspace",
                    db_path=root / "workspace-memory.sqlite3",
                    export_dir=root,
                    workspace=guessed_workspace,
                )
            )
            derived_workspace = guessed_workspace
        if profile_store is None or workspace_store is None:
            raise ValueError("profile_store and workspace_store are required")
        self.profile_store = profile_store
        self.workspace_store = workspace_store
        self.legacy_store = derived_legacy
        self.workspace_id = derived_workspace or workspace_store.space.workspace
        self.extractor = extractor or MemoryExtractor()
        self._prepared = False
        self._preparing = False

    @classmethod
    def from_config(cls, config: "AppConfig") -> "MemoryManager":
        return cls(
            profile_store=SQLiteMemoryStore(
                MemorySpace(
                    scope="private",
                    db_path=config.profile_memory_db,
                    export_dir=config.profile_memory_dir,
                )
            ),
            workspace_store=SQLiteMemoryStore(
                MemorySpace(
                    scope="workspace",
                    db_path=config.workspace_memory_db,
                    export_dir=config.memory_dir,
                    workspace=str(config.root_dir),
                )
            ),
            legacy_store=MemoryStore(config.memory_dir),
            workspace_id=str(config.root_dir),
        )

    def prepare(self) -> None:
        if self._prepared or self._preparing:
            return
        self._preparing = True
        self.profile_store.ensure_structure()
        self.workspace_store.ensure_structure()
        try:
            self._import_legacy_markdown()
            self.rebuild_digests()
            self._prepared = True
        finally:
            self._preparing = False

    def memory_instruction_block(self) -> str:
        self._ensure_prepared()
        pending = len(self.list_pending_confirmations())
        if pending == 0:
            return MEMORY_INSTRUCTIONS
        return (
            f"{MEMORY_INSTRUCTIONS} "
            f"There are {pending} pending memory candidates awaiting confirmation; do not treat them as durable facts yet."
        )

    def list_pending_confirmations(self) -> list[MemoryObservation]:
        self._ensure_prepared()
        return [
            *self.profile_store.list_pending_confirmations(),
            *self.workspace_store.list_pending_confirmations(),
        ]

    def recall(self, context: RecallContext | str, limit: int = 5) -> list[RecalledMemory]:
        self._ensure_prepared()
        if isinstance(context, str):
            context = RecallContext(query=context, active_workspace=self.workspace_id)

        candidate_query = self._candidate_query(context)
        candidates: dict[str, tuple[MemoryFact, float]] = {}
        for store in self._stores_for_context(context):
            search_limit = max(limit * 6, 18)
            if candidate_query.strip():
                found = store.search_facts(candidate_query, limit=search_limit)
            else:
                found = [(fact, 0.0) for fact in store.list_facts()[:search_limit]]
            if not found:
                found = [(fact, 0.0) for fact in store.list_facts()[:search_limit]]
            for fact, base_score in found:
                current = candidates.get(fact.fact_id)
                if current is None or current[1] < base_score:
                    candidates[fact.fact_id] = (fact, base_score)
            for fact in store.list_facts(memory_types=("commitment", "event")):
                current = candidates.get(fact.fact_id)
                base = 1.25 if fact.status == "active" else 0.3
                if current is None or current[1] < base:
                    candidates[fact.fact_id] = (fact, base)
        ranked = recall_facts(context, list(candidates.values()), limit=max(limit, 8))
        if len(ranked) > limit:
            ranked = self._maybe_rerank(context, ranked)[:limit]
        return ranked[:limit]

    def record_observations(
        self, observations: list[MemoryObservation] | tuple[MemoryObservation, ...]
    ) -> RecordObservationsResult:
        self._ensure_prepared()
        stored_observations: list[MemoryObservation] = []
        promoted_facts: list[MemoryFact] = []
        pending: list[MemoryObservation] = []
        for observation in observations:
            routed = self._route_observation(observation)
            target = self._store_for_scope(routed.scope or "private")
            recorded, promoted = target.record_observation(routed)
            stored_observations.append(recorded)
            if promoted is not None:
                promoted_facts.append(promoted)
            if recorded.requires_confirmation:
                pending.append(recorded)
        if promoted_facts:
            self.rebuild_digests()
        return RecordObservationsResult(
            observations=tuple(stored_observations),
            promoted_facts=tuple(promoted_facts),
            pending_confirmations=tuple(pending),
        )

    def capture_turn(
        self,
        messages: list,
        *,
        active_workspace: str | None,
        touched_paths: tuple[str, ...] = (),
        session_id: str = "default",
    ) -> RecordObservationsResult:
        self._ensure_prepared()
        observations = self.extractor.extract(
            messages,
            active_workspace=active_workspace or self.workspace_id,
            touched_paths=touched_paths,
            session_id=session_id,
        )
        if not observations:
            return RecordObservationsResult(observations=(), promoted_facts=(), pending_confirmations=())
        return self.record_observations(observations)

    def consolidate(self) -> dict[str, dict[str, int]]:
        self._ensure_prepared()
        result = {
            "private": self.profile_store.consolidate(),
            "workspace": self.workspace_store.consolidate(),
        }
        self.rebuild_digests()
        return result

    def forget(self, identifier: str, *, scope: MemoryScope | None = None, reason: str = "user_request") -> int:
        self._ensure_prepared()
        stores = [self._store_for_scope(scope)] if scope else [self.profile_store, self.workspace_store]
        forgotten = 0
        for store in stores:
            forgotten += store.forget(identifier, reason=reason)
        if forgotten:
            self.rebuild_digests()
        return forgotten

    def rebuild_digests(self) -> dict[str, str]:
        self._ensure_prepared_dirs()
        return {
            "private": self.profile_store.rebuild_digests(),
            "workspace": self.workspace_store.rebuild_digests(),
        }

    def _maybe_rerank(self, context: RecallContext, memories: list[RecalledMemory]) -> list[RecalledMemory]:
        prioritized = sorted(
            memories,
            key=lambda item: (
                item.fact.memory_type in {"commitment", "event"},
                item.fact.scope == "workspace" and item.fact.workspace == context.active_workspace,
                item.score,
            ),
            reverse=True,
        )
        return prioritized

    def _candidate_query(self, context: RecallContext) -> str:
        parts = [
            context.query,
            " ".join(context.participants),
            " ".join(context.todos),
            " ".join(context.source_hints),
            " ".join(Path(path).name for path in context.touched_paths),
        ]
        return " ".join(part for part in parts if part).strip()

    def _route_observation(self, observation: MemoryObservation) -> MemoryObservation:
        requires_confirmation = observation.requires_confirmation or observation.sensitivity != "normal"
        scope = observation.scope or self._default_scope_for_type(observation.memory_type, observation)
        workspace = observation.workspace
        if observation.sensitivity == "secret":
            scope = "private"
            workspace = None
        elif scope == "workspace":
            workspace = workspace or self.workspace_id
        if requires_confirmation and scope == "workspace":
            scope = "private"
            workspace = None
        status = "pending_confirmation" if requires_confirmation else observation.status
        dedupe_key = observation.dedupe_key or dedupe_key_for(
            scope=scope,
            memory_type=observation.memory_type,
            title=observation.title,
            workspace=workspace,
            entity_refs=observation.entity_refs,
        )
        return replace(
            observation,
            scope=scope,
            workspace=workspace,
            requires_confirmation=requires_confirmation,
            status=status,
            dedupe_key=dedupe_key,
        )

    def _default_scope_for_type(
        self, memory_type: MemoryType, observation: MemoryObservation
    ) -> MemoryScope:
        if memory_type in PRIVATE_DEFAULT_TYPES:
            return "private"
        if memory_type in WORKSPACE_DEFAULT_TYPES:
            return "workspace"
        if memory_type in {"commitment", "event"}:
            source_type = str(observation.metadata.get("source_type", "")).lower()
            if observation.workspace or "workspace" in source_type or "tool" in source_type:
                return "workspace"
            if any(token in observation.detail.lower() for token in ("repo", "project", "workspace", "项目", "仓库")):
                return "workspace"
        return "private"

    def _store_for_scope(self, scope: MemoryScope) -> SQLiteMemoryStore:
        if scope == "workspace":
            return self.workspace_store
        return self.profile_store

    def _stores_for_context(self, context: RecallContext) -> list[SQLiteMemoryStore]:
        stores: list[SQLiteMemoryStore] = []
        if "private" in context.allowed_scopes:
            stores.append(self.profile_store)
        if "workspace" in context.allowed_scopes:
            stores.append(self.workspace_store)
        return stores

    def _import_legacy_markdown(self) -> None:
        if self.legacy_store is None:
            return
        if (
            self.profile_store.count_facts() > 0
            or self.workspace_store.count_facts() > 0
            or self.profile_store.count_observations() > 0
            or self.workspace_store.count_observations() > 0
        ):
            return
        entries = self.legacy_store.list_entries()
        if not entries:
            return
        for entry in entries:
            observation = self._legacy_entry_to_observation(entry)
            self.record_observations([observation])

    def _legacy_entry_to_observation(self, entry: MemoryEntry) -> MemoryObservation:
        memory_type = LEGACY_KIND_TO_TYPE.get(entry.kind, "reference")
        scope: MemoryScope = "workspace" if entry.kind in {"project", "reference"} else "private"
        workspace = self.workspace_id if scope == "workspace" else None
        summary = entry.description.strip() or entry.content.strip().splitlines()[0]
        return MemoryObservation(
            title=entry.name,
            summary=summary,
            detail=entry.content.strip(),
            memory_type=memory_type,
            scope=scope,
            sensitivity="normal",
            confidence=0.75,
            observed_at=entry.updated_at,
            last_verified_at=entry.updated_at,
            source_ref=str(entry.path),
            entity_refs=(),
            status="recorded",
            workspace=workspace,
            requires_confirmation=False,
            dedupe_key=dedupe_key_for(
                scope=scope,
                memory_type=memory_type,
                title=entry.name,
                workspace=workspace,
            ),
            metadata={"legacy_kind": entry.kind, "legacy_path": str(entry.path)},
            evidence=(
                EvidenceRef(
                    source_type="legacy_markdown",
                    source_ref=str(entry.path),
                    snippet=summary,
                ),
            ),
        )

    def _ensure_prepared(self) -> None:
        if self._prepared or self._preparing:
            return
        self.prepare()

    def _ensure_prepared_dirs(self) -> None:
        self.profile_store.ensure_structure()
        self.workspace_store.ensure_structure()
