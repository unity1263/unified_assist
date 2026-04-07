from __future__ import annotations

import re
from dataclasses import replace
from datetime import timedelta
from typing import Iterable

from unified_assist.memory.types import (
    EvidenceRef,
    MemoryObservation,
    MemoryType,
    SensitivityLevel,
    TIME_BOUND_TYPES,
    utc_now,
)
from unified_assist.messages.models import AssistantMessage, Message, ToolResultMessage, UserMessage


PROPER_NAME_RE = re.compile(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b")


class MemoryExtractor:
    def extract(
        self,
        messages: Iterable[Message],
        *,
        active_workspace: str | None = None,
        touched_paths: tuple[str, ...] = (),
        session_id: str = "default",
    ) -> list[MemoryObservation]:
        observations: list[MemoryObservation] = []
        for message in messages:
            if isinstance(message, UserMessage) and not message.is_meta:
                observations.extend(
                    self._extract_from_text(
                        message.content,
                        source_type="user_message",
                        source_ref=f"session://{session_id}/user",
                        active_workspace=active_workspace,
                        touched_paths=touched_paths,
                    )
                )
            elif isinstance(message, ToolResultMessage):
                combined = "\n".join(result.content for result in message.results if result.content.strip()).strip()
                if not combined:
                    continue
                observations.extend(
                    self._extract_from_text(
                        combined,
                        source_type=message.source_tool or "tool_result",
                        source_ref=f"session://{session_id}/tool/{message.source_tool or 'unknown'}",
                        active_workspace=active_workspace,
                        touched_paths=touched_paths,
                        allow_implicit=False,
                    )
                )
            elif isinstance(message, AssistantMessage) and message.text.strip():
                if "remember" not in message.text.lower() and "记住" not in message.text:
                    continue
                observations.extend(
                    self._extract_from_text(
                        message.text,
                        source_type="assistant_message",
                        source_ref=f"session://{session_id}/assistant",
                        active_workspace=active_workspace,
                        touched_paths=touched_paths,
                        allow_implicit=False,
                    )
                )
        return self._dedupe(observations)

    def _extract_from_text(
        self,
        text: str,
        *,
        source_type: str,
        source_ref: str,
        active_workspace: str | None,
        touched_paths: tuple[str, ...],
        allow_implicit: bool = True,
    ) -> list[MemoryObservation]:
        raw = text.strip()
        if not raw:
            return []
        lowered = raw.lower()
        explicit = self._strip_explicit_memory_prefix(raw)
        should_consider = explicit != raw or allow_implicit
        if not should_consider:
            return []

        memory_type = self._infer_memory_type(explicit if explicit != raw else raw, lowered)
        if memory_type is None:
            return []

        sensitivity = self._infer_sensitivity(raw)
        requires_confirmation = self._requires_confirmation(raw, memory_type, sensitivity)
        title = self._build_title(explicit if explicit != raw else raw)
        summary = self._build_summary(explicit if explicit != raw else raw)
        expires_at = self._infer_expiry(memory_type, raw)
        entities = self._extract_entities(raw)
        scope = None
        workspace = None
        if memory_type in ("workspace", "reference"):
            scope = "workspace"
            workspace = active_workspace
        elif memory_type in TIME_BOUND_TYPES and self._looks_workspace_related(raw, touched_paths):
            scope = "workspace"
            workspace = active_workspace
        if sensitivity == "secret":
            scope = "private"
            workspace = None

        observation = MemoryObservation(
            title=title,
            summary=summary,
            detail=raw,
            memory_type=memory_type,
            scope=scope,
            sensitivity=sensitivity,
            confidence=0.65 if explicit != raw else 0.55,
            observed_at=utc_now(),
            expires_at=expires_at,
            source_ref=source_ref,
            entity_refs=entities,
            requires_confirmation=requires_confirmation,
            status="pending_confirmation" if requires_confirmation else "candidate",
            workspace=workspace,
            metadata={"source_type": source_type, "touched_paths": list(touched_paths)},
            evidence=(EvidenceRef(source_type=source_type, source_ref=source_ref, snippet=summary),),
        )
        return [observation]

    def _strip_explicit_memory_prefix(self, text: str) -> str:
        patterns = (
            r"^\s*(remember|note|memorize)\s+(that\s+)?",
            r"^\s*(请)?记住[:：]?\s*",
            r"^\s*记一下[:：]?\s*",
        )
        for pattern in patterns:
            updated = re.sub(pattern, "", text, flags=re.IGNORECASE).strip()
            if updated != text.strip():
                return updated
        return text.strip()

    def _infer_memory_type(self, text: str, lowered: str) -> MemoryType | None:
        if any(token in lowered for token in ("my name is", "i am ", "i work at", "我叫", "我的名字", "我是")):
            return "profile"
        if any(token in lowered for token in ("i prefer", "i like", "i dislike", "don't like", "偏好", "喜欢", "不喜欢", "最好")):
            return "preference"
        if any(token in lowered for token in ("my mom", "my dad", "alice", "bob", "birthday", "vegetarian", "妈妈", "爸爸")):
            return "person"
        if any(token in lowered for token in ("team convention", "workspace policy", "repo policy", "in this project", "仓库约定", "项目约定")):
            return "workspace"
        if any(token in lowered for token in ("reference", "docs", "playbook", "runbook", "文档", "资料")):
            return "reference"
        if any(token in lowered for token in ("every day", "every week", "usually", "normally", "每天", "每周", "通常")):
            return "routine"
        if any(token in lowered for token in ("deadline", "due", "must", "todo", "承诺", "截止", "要完成")):
            return "commitment"
        if any(token in lowered for token in ("meeting", "appointment", "tomorrow", "next week", "calendar", "会议", "明天", "下周")):
            return "event"
        if "remember" in lowered or "记住" in text:
            return "preference"
        return None

    def _infer_sensitivity(self, text: str) -> SensitivityLevel:
        lowered = text.lower()
        if any(token in lowered for token in ("password", "api key", "token", "secret", "ssn", "密码", "密钥")):
            return "secret"
        if any(
            token in lowered
            for token in ("salary", "bank", "medical", "health", "address", "phone", "银行卡", "住址", "医疗")
        ):
            return "sensitive"
        return "normal"

    def _requires_confirmation(
        self,
        text: str,
        memory_type: MemoryType,
        sensitivity: SensitivityLevel,
    ) -> bool:
        lowered = text.lower()
        if sensitivity != "normal":
            return True
        if any(token in lowered for token in ("maybe", "might", "probably", "not sure", "可能", "也许", "不确定")):
            return True
        if memory_type in TIME_BOUND_TYPES and not self._contains_time_hint(lowered):
            return True
        return False

    def _contains_time_hint(self, lowered: str) -> bool:
        return any(
            token in lowered
            for token in (
                "today",
                "tomorrow",
                "next week",
                "monday",
                "tuesday",
                "deadline",
                "今天",
                "明天",
                "下周",
                "周",
            )
        )

    def _infer_expiry(self, memory_type: MemoryType, text: str):
        if memory_type not in TIME_BOUND_TYPES:
            return None
        lowered = text.lower()
        now = utc_now()
        if "tomorrow" in lowered or "明天" in text:
            return now + timedelta(days=1)
        if "next week" in lowered or "下周" in text:
            return now + timedelta(days=7)
        if "today" in lowered or "今天" in text:
            return now + timedelta(hours=12)
        return None

    def _looks_workspace_related(self, text: str, touched_paths: tuple[str, ...]) -> bool:
        lowered = text.lower()
        return bool(touched_paths) or any(
            token in lowered for token in ("repo", "project", "workspace", "teammate", "仓库", "项目", "工作区")
        )

    def _build_title(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if len(cleaned) <= 72:
            return cleaned
        return cleaned[:69].rstrip() + "..."

    def _build_summary(self, text: str) -> str:
        line = text.strip().splitlines()[0].strip()
        if len(line) <= 160:
            return line
        return line[:157].rstrip() + "..."

    def _extract_entities(self, text: str) -> tuple[str, ...]:
        matches = {match.group(0).strip() for match in PROPER_NAME_RE.finditer(text)}
        for marker in ("mom", "dad", "妈妈", "爸爸"):
            if marker in text.lower() or marker in text:
                matches.add(marker)
        return tuple(sorted(match for match in matches if match))

    def _dedupe(self, observations: list[MemoryObservation]) -> list[MemoryObservation]:
        deduped: dict[tuple[str, str, str], MemoryObservation] = {}
        for observation in observations:
            key = (observation.memory_type, observation.title, observation.source_ref)
            if key not in deduped:
                deduped[key] = observation
                continue
            existing = deduped[key]
            deduped[key] = replace(
                existing,
                confidence=max(existing.confidence, observation.confidence),
                requires_confirmation=existing.requires_confirmation or observation.requires_confirmation,
            )
        return list(deduped.values())
