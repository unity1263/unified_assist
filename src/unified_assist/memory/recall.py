from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from unified_assist.memory.freshness import age_days, freshness_note, freshness_text
from unified_assist.memory.store import MemoryEntry
from unified_assist.memory.types import MemoryFact, RecallContext


WORD_RE = re.compile(r"[a-zA-Z0-9_\u4e00-\u9fff]+")


@dataclass(frozen=True, slots=True)
class RecalledMemory:
    fact: MemoryFact
    score: float
    excerpt: str
    freshness: str
    freshness_note: str
    provenance: str
    verification_note: str

    @property
    def entry(self) -> MemoryFact:
        return self.fact


def _tokenize(text: str) -> Counter[str]:
    return Counter(token.lower() for token in WORD_RE.findall(text))


def score_entry(query: str, entry: MemoryEntry) -> float:
    query_terms = _tokenize(query)
    if not query_terms:
        return 0.0
    entry_terms = _tokenize(f"{entry.name} {entry.description} {entry.content}")
    overlap = sum(min(entry_terms[token], count) for token, count in query_terms.items())
    if overlap == 0:
        return 0.0
    recency_bonus = 1 / (1 + age_days(entry.updated_at))
    return float(overlap) + recency_bonus


def _ranked_memories(query: str, entries: list[MemoryEntry]) -> list[tuple[float, MemoryEntry]]:
    return sorted(
        ((score_entry(query, entry), entry) for entry in entries),
        key=lambda item: item[0],
        reverse=True,
    )


def recall_memories(query: str, entries: list[MemoryEntry], limit: int = 5) -> list[MemoryEntry]:
    ranked = _ranked_memories(query, entries)
    return [entry for score, entry in ranked[:limit] if score > 0]


def recall_memory_context(
    query: str,
    entries: list[MemoryEntry],
    limit: int = 5,
    *,
    now: datetime | None = None,
    excerpt_chars: int = 220,
) -> list[RecalledMemory]:
    ranked = _ranked_memories(query, entries)
    context: list[RecalledMemory] = []
    for score, entry in ranked[:limit]:
        if score <= 0:
            continue
        fact = MemoryFact(
            fact_id=str(entry.path),
            title=entry.name,
            summary=entry.description,
            detail=entry.content,
            memory_type=entry.kind if entry.kind != "project" else "workspace",
            scope="workspace" if entry.kind in {"project", "reference"} else "private",
            sensitivity="normal",
            confidence=0.5,
            observed_at=entry.updated_at,
            last_verified_at=entry.updated_at,
            expires_at=None,
            source_ref=str(entry.path),
            entity_refs=(),
            status="active",
            export_path=entry.path,
        )
        excerpt = _build_excerpt(fact, max_chars=excerpt_chars)
        current_freshness = freshness_text(entry.updated_at, now=now)
        current_note = freshness_note(entry.updated_at, now=now)
        context.append(
            RecalledMemory(
                fact=fact,
                score=score,
                excerpt=excerpt,
                freshness=current_freshness,
                freshness_note=current_note,
                provenance=str(entry.path),
                verification_note=_verification_note(fact, current_note),
            )
        )
    return context


def recall_facts(
    context: RecallContext,
    candidates: Iterable[tuple[MemoryFact, float] | MemoryFact],
    *,
    limit: int = 5,
    now: datetime | None = None,
) -> list[RecalledMemory]:
    ranked: list[tuple[float, MemoryFact]] = []
    for item in candidates:
        if isinstance(item, tuple):
            fact, base_score = item
        else:
            fact, base_score = item, 0.0
        total = score_fact(context, fact, base_score=base_score)
        if total <= 0:
            continue
        ranked.append((total, fact))
    ranked.sort(key=lambda item: item[0], reverse=True)
    result: list[RecalledMemory] = []
    seen: set[str] = set()
    for score, fact in ranked:
        if fact.fact_id in seen:
            continue
        seen.add(fact.fact_id)
        current_freshness = freshness_text(fact.last_verified_at, now=now or context.current_time)
        current_note = freshness_note(fact.last_verified_at, now=now or context.current_time)
        result.append(
            RecalledMemory(
                fact=fact,
                score=score,
                excerpt=_build_excerpt(fact),
                freshness=current_freshness,
                freshness_note=current_note,
                provenance=_provenance_text(fact),
                verification_note=_verification_note(fact, current_note),
            )
        )
        if len(result) >= limit:
            break
    return result


def score_fact(context: RecallContext, fact: MemoryFact, *, base_score: float = 0.0) -> float:
    if fact.status == "deleted":
        return 0.0
    if fact.scope not in context.allowed_scopes:
        return 0.0
    if fact.scope == "workspace" and context.active_workspace and fact.workspace:
        if fact.workspace != context.active_workspace:
            return 0.0

    search_text = " ".join(
        part
        for part in (
            context.query,
            " ".join(context.participants),
            " ".join(context.todos),
            " ".join(os.path.basename(path) for path in context.touched_paths),
            " ".join(context.source_hints),
        )
        if part
    )
    query_terms = _tokenize(search_text)
    fact_terms = _tokenize(
        " ".join(
            (
                fact.title,
                fact.summary,
                fact.detail,
                " ".join(fact.entity_refs),
                fact.source_ref,
                " ".join(str(item) for item in fact.metadata.get("touched_paths", [])),
            )
        )
    )

    overlap = sum(min(fact_terms[token], count) for token, count in query_terms.items())
    score = float(base_score + overlap)

    if context.active_workspace and fact.scope == "workspace":
        score += 2.0
    if fact.memory_type in {"commitment", "event"} and fact.status == "active":
        score += 1.5
    if fact.memory_type in {"person", "relationship"} and context.participants:
        score += 1.5
    if fact.sensitivity == "secret":
        score += 0.5
    if fact.expires_at is not None and fact.expires_at >= context.current_time:
        remaining_days = (fact.expires_at - context.current_time).total_seconds() / 86400
        if remaining_days <= 7:
            score += 2.0
    if any(participant.lower() in fact.title.lower() for participant in context.participants):
        score += 1.5
    if any(hint and hint.lower() in fact.source_ref.lower() for hint in context.source_hints):
        score += 1.0
    touched_names = {os.path.basename(path).lower() for path in context.touched_paths}
    if touched_names and any(name in fact.detail.lower() or name in fact.source_ref.lower() for name in touched_names):
        score += 1.0

    recency_bonus = 1 / (1 + age_days(fact.last_verified_at, now=context.current_time))
    score += recency_bonus
    if fact.status == "closed":
        score -= 0.75
    if fact.sensitivity == "secret":
        score -= 0.25
    return score


def _build_excerpt(fact: MemoryFact, *, max_chars: int = 220) -> str:
    if fact.sensitivity == "secret":
        return f"Secret memory exists for '{fact.title}'. Ask the user before using exact details."
    base = fact.summary.strip() or fact.detail.strip() or fact.title
    if len(base) <= max_chars:
        return base
    return base[: max_chars - 3].rstrip() + "..."


def _provenance_text(fact: MemoryFact) -> str:
    source = fact.source_ref or "memory observation"
    if fact.scope == "workspace" and fact.workspace:
        return f"{source} ({fact.workspace})"
    return source


def _verification_note(fact: MemoryFact, freshness: str) -> str:
    notes: list[str] = []
    if freshness:
        notes.append(freshness)
    if fact.status == "closed":
        notes.append("This memory may describe completed work or a past event.")
    if fact.expires_at is not None:
        if fact.expires_at < datetime.now(fact.expires_at.tzinfo):
            notes.append("This memory has passed its expiry window.")
        else:
            notes.append("Verify the time-sensitive details before relying on them.")
    if fact.sensitivity == "secret":
        notes.append("Do not reveal the secret verbatim without the user's consent.")
    if not notes:
        return ""
    return " ".join(notes)
