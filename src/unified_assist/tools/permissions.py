from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PermissionMode(StrEnum):
    DEFAULT = "default"
    ACCEPT_EDITS = "accept_edits"
    READ_ONLY = "read_only"
    PLAN = "plan"


@dataclass(frozen=True, slots=True)
class PermissionDecision:
    behavior: str
    reason: str = ""


def allow_decision() -> PermissionDecision:
    return PermissionDecision("allow")


def deny_decision(reason: str) -> PermissionDecision:
    return PermissionDecision("deny", reason)


def ask_decision(reason: str) -> PermissionDecision:
    return PermissionDecision("ask", reason)


def decide_permission(mode: PermissionMode, *, is_read_only: bool) -> PermissionDecision:
    if mode == PermissionMode.READ_ONLY and not is_read_only:
        return deny_decision("permission mode is read_only")
    if mode == PermissionMode.PLAN and not is_read_only:
        return deny_decision("permission mode is plan")
    return allow_decision()
