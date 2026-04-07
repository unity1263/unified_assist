from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from unified_assist.memory.types import (
    EvidenceRef,
    MemoryFact,
    MemoryObservation,
    MemorySpace,
    MemoryStatus,
    ObservationStatus,
    utc_now,
)
from unified_assist.utils.paths import ensure_dir, slugify


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _decode_json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def dedupe_key_for(
    *,
    scope: str,
    memory_type: str,
    title: str,
    workspace: str | None = None,
    entity_refs: tuple[str, ...] = (),
) -> str:
    suffix = workspace or "global"
    entity_part = "-".join(slugify(item) for item in entity_refs if item.strip())
    return ":".join(
        part
        for part in (
            scope,
            memory_type,
            slugify(title),
            slugify(suffix),
            entity_part or None,
        )
        if part
    )


class SQLiteMemoryStore:
    def __init__(self, space: MemorySpace) -> None:
        self.space = space
        self._fts_enabled = True

    def ensure_structure(self) -> None:
        ensure_dir(self.space.db_path.parent)
        ensure_dir(self.space.export_dir)
        ensure_dir(self.space.export_dir / "topics")
        with self._connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS entities (
                    entity_id TEXT PRIMARY KEY,
                    canonical_name TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    aliases_json TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    source_ref TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS facts (
                    fact_id TEXT PRIMARY KEY,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    sensitivity TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    observed_at TEXT NOT NULL,
                    last_verified_at TEXT NOT NULL,
                    expires_at TEXT,
                    source_ref TEXT NOT NULL,
                    entity_refs_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    workspace TEXT,
                    provenance_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS observations (
                    observation_id TEXT PRIMARY KEY,
                    dedupe_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    memory_type TEXT NOT NULL,
                    scope TEXT NOT NULL,
                    sensitivity TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    observed_at TEXT NOT NULL,
                    last_verified_at TEXT,
                    expires_at TEXT,
                    source_ref TEXT NOT NULL,
                    entity_refs_json TEXT NOT NULL,
                    status TEXT NOT NULL,
                    workspace TEXT,
                    requires_confirmation INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evidence (
                    evidence_id TEXT PRIMARY KEY,
                    owner_kind TEXT NOT NULL,
                    owner_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_ref TEXT NOT NULL,
                    snippet TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tombstones (
                    tombstone_id TEXT PRIMARY KEY,
                    dedupe_key TEXT NOT NULL UNIQUE,
                    fact_id TEXT,
                    reason TEXT NOT NULL,
                    source_ref TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS digests (
                    digest_id TEXT PRIMARY KEY,
                    scope TEXT NOT NULL,
                    digest_kind TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_facts_scope_status ON facts(scope, status);
                CREATE INDEX IF NOT EXISTS idx_facts_type_status ON facts(memory_type, status);
                CREATE INDEX IF NOT EXISTS idx_observations_status ON observations(status);
                CREATE INDEX IF NOT EXISTS idx_tombstones_dedupe ON tombstones(dedupe_key);
                """
            )
            try:
                connection.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS facts_fts
                    USING fts5(
                        fact_id UNINDEXED,
                        title,
                        summary,
                        detail,
                        entity_refs,
                        source_ref
                    );
                    """
                )
                self._fts_enabled = True
            except sqlite3.OperationalError:
                self._fts_enabled = False

    def count_facts(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM facts").fetchone()
        return int(row["count"]) if row is not None else 0

    def count_observations(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COUNT(*) AS count FROM observations").fetchone()
        return int(row["count"]) if row is not None else 0

    def list_facts(
        self,
        *,
        statuses: tuple[MemoryStatus, ...] = ("active", "closed", "pending_confirmation"),
        memory_types: tuple[str, ...] | None = None,
    ) -> list[MemoryFact]:
        query = "SELECT * FROM facts"
        conditions: list[str] = []
        params: list[object] = []
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            conditions.append(f"status IN ({placeholders})")
            params.extend(statuses)
        if memory_types:
            placeholders = ", ".join("?" for _ in memory_types)
            conditions.append(f"memory_type IN ({placeholders})")
            params.extend(memory_types)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY updated_at DESC, observed_at DESC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [self._row_to_fact(row) for row in rows]

    def list_pending_confirmations(self) -> list[MemoryObservation]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM observations WHERE requires_confirmation = 1 ORDER BY created_at DESC"
            ).fetchall()
        return [self._row_to_observation(row) for row in rows]

    def record_observation(
        self, observation: MemoryObservation
    ) -> tuple[MemoryObservation, MemoryFact | None]:
        self.ensure_structure()
        now = utc_now()
        resolved = self._resolve_observation(observation)
        promoted: MemoryFact | None = None
        with self._connect() as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute(
                """
                INSERT INTO observations (
                    observation_id,
                    dedupe_key,
                    title,
                    summary,
                    detail,
                    memory_type,
                    scope,
                    sensitivity,
                    confidence,
                    observed_at,
                    last_verified_at,
                    expires_at,
                    source_ref,
                    entity_refs_json,
                    status,
                    workspace,
                    requires_confirmation,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resolved.observation_id,
                    resolved.dedupe_key,
                    resolved.title,
                    resolved.summary,
                    resolved.detail,
                    resolved.memory_type,
                    resolved.scope,
                    resolved.sensitivity,
                    resolved.confidence,
                    _iso(resolved.observed_at),
                    _iso(resolved.last_verified_at),
                    _iso(resolved.expires_at),
                    resolved.source_ref,
                    _json(list(resolved.entity_refs)),
                    resolved.status,
                    resolved.workspace,
                    1 if resolved.requires_confirmation else 0,
                    _json(resolved.metadata),
                    _iso(now),
                ),
            )
            self._insert_evidence(
                connection,
                owner_kind="observation",
                owner_id=resolved.observation_id or "",
                evidence=resolved.evidence,
            )
            if not resolved.requires_confirmation and not self._has_tombstone(connection, resolved.dedupe_key):
                promoted = self._upsert_fact(connection, self._fact_from_observation(resolved))
        return resolved, promoted

    def upsert_fact(self, fact: MemoryFact, evidence: tuple[EvidenceRef, ...] = ()) -> MemoryFact | None:
        self.ensure_structure()
        with self._connect() as connection:
            if self._has_tombstone(connection, fact.dedupe_key or ""):
                return None
            stored = self._upsert_fact(connection, fact)
            self._insert_evidence(connection, owner_kind="fact", owner_id=stored.fact_id, evidence=evidence)
        return stored

    def search_facts(self, query: str, *, limit: int = 20) -> list[tuple[MemoryFact, float]]:
        self.ensure_structure()
        with self._connect() as connection:
            if self._fts_enabled:
                token_query = self._fts_query(query)
                if token_query:
                    try:
                        rows = connection.execute(
                            """
                            SELECT f.*, bm25(facts_fts) AS rank
                            FROM facts_fts
                            JOIN facts AS f ON f.fact_id = facts_fts.fact_id
                            WHERE facts_fts MATCH ?
                              AND f.status != 'deleted'
                            ORDER BY rank
                            LIMIT ?
                            """,
                            (token_query, limit),
                        ).fetchall()
                        return [(self._row_to_fact(row), float(-row["rank"])) for row in rows]
                    except sqlite3.OperationalError:
                        self._fts_enabled = False
            like = f"%{query.strip()}%"
            rows = connection.execute(
                """
                SELECT *
                FROM facts
                WHERE status != 'deleted'
                  AND (
                    title LIKE ?
                    OR summary LIKE ?
                    OR detail LIKE ?
                    OR source_ref LIKE ?
                  )
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (like, like, like, like, limit),
            ).fetchall()
        return [(self._row_to_fact(row), 0.0) for row in rows]

    def forget(self, identifier: str, *, reason: str = "user_request", source_ref: str = "") -> int:
        self.ensure_structure()
        now = utc_now()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT fact_id, dedupe_key
                FROM facts
                WHERE fact_id = ? OR dedupe_key = ? OR title = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (identifier, identifier, identifier),
            ).fetchone()
            if row is None:
                dedupe_key = identifier
                fact_id = None
            else:
                dedupe_key = str(row["dedupe_key"])
                fact_id = str(row["fact_id"])
            connection.execute(
                """
                INSERT OR REPLACE INTO tombstones (
                    tombstone_id,
                    dedupe_key,
                    fact_id,
                    reason,
                    source_ref,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (uuid4().hex, dedupe_key, fact_id, reason, source_ref, _iso(now)),
            )
            updated = connection.execute(
                """
                UPDATE facts
                SET status = 'deleted', updated_at = ?
                WHERE dedupe_key = ? OR fact_id = ?
                """,
                (_iso(now), dedupe_key, fact_id),
            ).rowcount
            if self._fts_enabled:
                connection.execute("DELETE FROM facts_fts WHERE fact_id = ?", (fact_id,))
        return int(updated)

    def consolidate(self, *, now: datetime | None = None) -> dict[str, int]:
        self.ensure_structure()
        current = now or utc_now()
        closed = 0
        archived = 0
        with self._connect() as connection:
            closed = connection.execute(
                """
                UPDATE facts
                SET status = 'closed', updated_at = ?
                WHERE status = 'active'
                  AND memory_type IN ('commitment', 'event')
                  AND expires_at IS NOT NULL
                  AND expires_at < ?
                """,
                (_iso(current), _iso(current)),
            ).rowcount
            archived = connection.execute(
                """
                UPDATE observations
                SET status = 'archived'
                WHERE status IN ('candidate', 'recorded')
                  AND requires_confirmation = 0
                  AND confidence < 0.5
                  AND observed_at < ?
                """,
                (_iso(current - timedelta(days=7)),),
            ).rowcount
        return {"closed_commitments": int(closed), "archived_observations": int(archived)}

    def rebuild_digests(self) -> str:
        self.ensure_structure()
        facts = self.list_facts()
        now = utc_now()
        sections: dict[str, list[MemoryFact]] = {}
        for fact in facts:
            sections.setdefault(fact.memory_type, []).append(fact)

        index_lines = [f"# {self.space.scope.title()} Memory Index", ""]
        if not facts:
            index_lines.append("No durable memories recorded yet.")
        else:
            index_lines.append(
                f"Canonical store: `{self.space.db_path.name}`. Generated {now.date().isoformat()}."
            )
            index_lines.append("")
            for memory_type in sorted(sections):
                index_lines.append(f"## {memory_type.title()}")
                index_lines.append("")
                for fact in sections[memory_type]:
                    summary = fact.summary or fact.detail.splitlines()[0]
                    marker = " [secret]" if fact.sensitivity == "secret" else ""
                    index_lines.append(f"- {fact.title}{marker}: {summary}")
                index_lines.append("")
        index_body = "\n".join(index_lines).strip() + "\n"
        (self.space.export_dir / "MEMORY.md").write_text(index_body, encoding="utf-8")

        with self._connect() as connection:
            connection.execute("DELETE FROM digests WHERE scope = ?", (self.space.scope,))
            connection.execute(
                """
                INSERT INTO digests (digest_id, scope, digest_kind, slug, title, body, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    self.space.scope,
                    "index",
                    "memory-index",
                    f"{self.space.scope.title()} Memory Index",
                    index_body,
                    _iso(now),
                ),
            )
            for memory_type, items in sections.items():
                topic_path = self.space.export_dir / "topics" / f"{memory_type}.md"
                topic_lines = [f"# {memory_type.title()}"]
                topic_lines.append("")
                for fact in items:
                    topic_lines.append(f"## {fact.title}")
                    topic_lines.append("")
                    topic_lines.append(f"- Scope: {fact.scope}")
                    topic_lines.append(f"- Sensitivity: {fact.sensitivity}")
                    topic_lines.append(f"- Confidence: {fact.confidence:.2f}")
                    topic_lines.append(f"- Source: {fact.source_ref or 'unknown'}")
                    topic_lines.append(f"- Last verified: {_iso(fact.last_verified_at) or 'unknown'}")
                    topic_lines.append("")
                    topic_lines.append(fact.detail.strip() or fact.summary.strip())
                    topic_lines.append("")
                topic_body = "\n".join(topic_lines).strip() + "\n"
                topic_path.write_text(topic_body, encoding="utf-8")
                connection.execute(
                    """
                    INSERT INTO digests (digest_id, scope, digest_kind, slug, title, body, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        uuid4().hex,
                        self.space.scope,
                        "topic",
                        memory_type,
                        memory_type.title(),
                        topic_body,
                        _iso(now),
                    ),
                )
        return index_body

    def import_legacy_entries(
        self,
        entries: list[Any],
        *,
        mapper: callable,
    ) -> int:
        imported = 0
        for entry in entries:
            observation = mapper(entry)
            if observation is None:
                continue
            _, promoted = self.record_observation(observation)
            if promoted is not None:
                imported += 1
        return imported

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.space.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _resolve_observation(self, observation: MemoryObservation) -> MemoryObservation:
        dedupe_key = observation.dedupe_key or dedupe_key_for(
            scope=observation.scope or self.space.scope,
            memory_type=observation.memory_type,
            title=observation.title,
            workspace=observation.workspace or self.space.workspace,
            entity_refs=observation.entity_refs,
        )
        return replace(
            observation,
            scope=observation.scope or self.space.scope,
            workspace=observation.workspace or self.space.workspace,
            observation_id=observation.observation_id or uuid4().hex,
            last_verified_at=observation.last_verified_at or observation.observed_at,
            dedupe_key=dedupe_key,
        )

    def _fact_from_observation(self, observation: MemoryObservation) -> MemoryFact:
        observed_at = observation.observed_at
        last_verified_at = observation.last_verified_at or observed_at
        status: MemoryStatus = "active"
        if observation.requires_confirmation:
            status = "pending_confirmation"
        return MemoryFact(
            fact_id=uuid4().hex,
            title=observation.title,
            summary=observation.summary,
            detail=observation.detail,
            memory_type=observation.memory_type,
            scope=observation.scope or self.space.scope,
            sensitivity=observation.sensitivity,
            confidence=observation.confidence,
            observed_at=observed_at,
            last_verified_at=last_verified_at,
            expires_at=observation.expires_at,
            source_ref=observation.source_ref,
            entity_refs=observation.entity_refs,
            status=status,
            workspace=observation.workspace or self.space.workspace,
            dedupe_key=observation.dedupe_key,
            provenance={"source_ref": observation.source_ref, "space": self.space.scope},
            metadata=observation.metadata,
        )

    def _upsert_fact(self, connection: sqlite3.Connection, fact: MemoryFact) -> MemoryFact:
        current = connection.execute(
            "SELECT * FROM facts WHERE dedupe_key = ? LIMIT 1",
            (fact.dedupe_key,),
        ).fetchone()
        if current is None:
            stored = replace(
                fact,
                fact_id=fact.fact_id or uuid4().hex,
                dedupe_key=fact.dedupe_key
                or dedupe_key_for(
                    scope=fact.scope,
                    memory_type=fact.memory_type,
                    title=fact.title,
                    workspace=fact.workspace,
                    entity_refs=fact.entity_refs,
                ),
            )
            now = utc_now()
            connection.execute(
                """
                INSERT INTO facts (
                    fact_id,
                    dedupe_key,
                    title,
                    summary,
                    detail,
                    memory_type,
                    scope,
                    sensitivity,
                    confidence,
                    observed_at,
                    last_verified_at,
                    expires_at,
                    source_ref,
                    entity_refs_json,
                    status,
                    workspace,
                    provenance_json,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    stored.fact_id,
                    stored.dedupe_key,
                    stored.title,
                    stored.summary,
                    stored.detail,
                    stored.memory_type,
                    stored.scope,
                    stored.sensitivity,
                    stored.confidence,
                    _iso(stored.observed_at),
                    _iso(stored.last_verified_at),
                    _iso(stored.expires_at),
                    stored.source_ref,
                    _json(list(stored.entity_refs)),
                    stored.status,
                    stored.workspace,
                    _json(stored.provenance),
                    _json(stored.metadata),
                    _iso(now),
                    _iso(now),
                ),
            )
            self._upsert_entities(connection, stored)
            self._sync_fts(connection, stored)
            return stored

        existing = self._row_to_fact(current)
        merged = replace(
            existing,
            title=fact.title or existing.title,
            summary=fact.summary or existing.summary,
            detail=fact.detail or existing.detail,
            sensitivity=fact.sensitivity if fact.sensitivity != "normal" else existing.sensitivity,
            confidence=max(existing.confidence, fact.confidence),
            observed_at=min(existing.observed_at, fact.observed_at),
            last_verified_at=max(existing.last_verified_at, fact.last_verified_at),
            expires_at=fact.expires_at or existing.expires_at,
            source_ref=fact.source_ref or existing.source_ref,
            entity_refs=tuple(sorted(set(existing.entity_refs) | set(fact.entity_refs))),
            status=self._merge_status(existing.status, fact.status),
            workspace=fact.workspace or existing.workspace,
            provenance={**existing.provenance, **fact.provenance},
            metadata={**existing.metadata, **fact.metadata},
        )
        connection.execute(
            """
            UPDATE facts
            SET
                title = ?,
                summary = ?,
                detail = ?,
                sensitivity = ?,
                confidence = ?,
                observed_at = ?,
                last_verified_at = ?,
                expires_at = ?,
                source_ref = ?,
                entity_refs_json = ?,
                status = ?,
                workspace = ?,
                provenance_json = ?,
                metadata_json = ?,
                updated_at = ?
            WHERE fact_id = ?
            """,
            (
                merged.title,
                merged.summary,
                merged.detail,
                merged.sensitivity,
                merged.confidence,
                _iso(merged.observed_at),
                _iso(merged.last_verified_at),
                _iso(merged.expires_at),
                merged.source_ref,
                _json(list(merged.entity_refs)),
                merged.status,
                merged.workspace,
                _json(merged.provenance),
                _json(merged.metadata),
                _iso(utc_now()),
                merged.fact_id,
            ),
        )
        self._upsert_entities(connection, merged)
        self._sync_fts(connection, merged)
        return merged

    def _merge_status(self, existing: MemoryStatus, incoming: MemoryStatus) -> MemoryStatus:
        if existing == "deleted" or incoming == "deleted":
            return "deleted"
        if existing == "pending_confirmation" and incoming == "active":
            return "active"
        if existing == "closed" and incoming == "active":
            return "active"
        if incoming == "pending_confirmation":
            return existing
        return incoming if incoming != "archived" else existing

    def _sync_fts(self, connection: sqlite3.Connection, fact: MemoryFact) -> None:
        if not self._fts_enabled:
            return
        connection.execute("DELETE FROM facts_fts WHERE fact_id = ?", (fact.fact_id,))
        if fact.status == "deleted":
            return
        connection.execute(
            """
            INSERT INTO facts_fts (fact_id, title, summary, detail, entity_refs, source_ref)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                fact.fact_id,
                fact.title,
                fact.summary,
                fact.detail,
                " ".join(fact.entity_refs),
                fact.source_ref,
            ),
        )

    def _insert_evidence(
        self,
        connection: sqlite3.Connection,
        *,
        owner_kind: str,
        owner_id: str,
        evidence: tuple[EvidenceRef, ...],
    ) -> None:
        if not evidence:
            return
        now = utc_now()
        for item in evidence:
            connection.execute(
                """
                INSERT INTO evidence (
                    evidence_id,
                    owner_kind,
                    owner_id,
                    source_type,
                    source_ref,
                    snippet,
                    metadata_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid4().hex,
                    owner_kind,
                    owner_id,
                    item.source_type,
                    item.source_ref,
                    item.snippet,
                    _json(item.metadata),
                    _iso(now),
                ),
            )

    def _upsert_entities(self, connection: sqlite3.Connection, fact: MemoryFact) -> None:
        now = utc_now()
        for entity in fact.entity_refs:
            entity_key = f"{fact.scope}:{slugify(entity)}"
            current = connection.execute(
                "SELECT entity_id, aliases_json FROM entities WHERE entity_id = ?",
                (entity_key,),
            ).fetchone()
            aliases = [entity]
            if current is not None:
                aliases = list(
                    sorted(set(_decode_json(str(current["aliases_json"]), [])) | {entity})
                )
                connection.execute(
                    """
                    UPDATE entities
                    SET canonical_name = ?, aliases_json = ?, updated_at = ?, source_ref = ?
                    WHERE entity_id = ?
                    """,
                    (entity, _json(aliases), _iso(now), fact.source_ref, entity_key),
                )
                continue
            connection.execute(
                """
                INSERT INTO entities (
                    entity_id,
                    canonical_name,
                    entity_type,
                    aliases_json,
                    scope,
                    source_ref,
                    metadata_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entity_key,
                    entity,
                    "person",
                    _json(aliases),
                    fact.scope,
                    fact.source_ref,
                    _json({}),
                    _iso(now),
                    _iso(now),
                ),
            )

    def _has_tombstone(self, connection: sqlite3.Connection, dedupe_key: str) -> bool:
        if not dedupe_key:
            return False
        row = connection.execute(
            "SELECT tombstone_id FROM tombstones WHERE dedupe_key = ? LIMIT 1",
            (dedupe_key,),
        ).fetchone()
        return row is not None

    def _fts_query(self, query: str) -> str:
        cleaned = [token for token in re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", query) if len(token) > 1]
        return " OR ".join(f"{token}*" for token in cleaned)

    def _row_to_fact(self, row: sqlite3.Row) -> MemoryFact:
        export_path = self.space.export_dir / "topics" / f"{row['memory_type']}.md"
        return MemoryFact(
            fact_id=str(row["fact_id"]),
            title=str(row["title"]),
            summary=str(row["summary"]),
            detail=str(row["detail"]),
            memory_type=str(row["memory_type"]),
            scope=str(row["scope"]),
            sensitivity=str(row["sensitivity"]),
            confidence=float(row["confidence"]),
            observed_at=_parse_datetime(str(row["observed_at"])) or utc_now(),
            last_verified_at=_parse_datetime(str(row["last_verified_at"])) or utc_now(),
            expires_at=_parse_datetime(row["expires_at"]),
            source_ref=str(row["source_ref"]),
            entity_refs=tuple(_decode_json(str(row["entity_refs_json"]), [])),
            status=str(row["status"]),
            workspace=row["workspace"],
            dedupe_key=str(row["dedupe_key"]),
            provenance=dict(_decode_json(str(row["provenance_json"]), {})),
            metadata=dict(_decode_json(str(row["metadata_json"]), {})),
            export_path=export_path,
        )

    def _row_to_observation(self, row: sqlite3.Row) -> MemoryObservation:
        return MemoryObservation(
            title=str(row["title"]),
            summary=str(row["summary"]),
            detail=str(row["detail"]),
            memory_type=str(row["memory_type"]),
            scope=str(row["scope"]),
            sensitivity=str(row["sensitivity"]),
            confidence=float(row["confidence"]),
            observed_at=_parse_datetime(str(row["observed_at"])) or utc_now(),
            last_verified_at=_parse_datetime(row["last_verified_at"]),
            expires_at=_parse_datetime(row["expires_at"]),
            source_ref=str(row["source_ref"]),
            entity_refs=tuple(_decode_json(str(row["entity_refs_json"]), [])),
            status=str(row["status"]),
            workspace=row["workspace"],
            requires_confirmation=bool(row["requires_confirmation"]),
            dedupe_key=str(row["dedupe_key"]),
            metadata=dict(_decode_json(str(row["metadata_json"]), {})),
            evidence=(),
            observation_id=str(row["observation_id"]),
        )
