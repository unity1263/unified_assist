from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PromptSection:
    name: str
    content: str
    priority: int = 100
    enabled: bool = True


def order_sections(sections: list[PromptSection]) -> list[PromptSection]:
    return sorted(
        [section for section in sections if section.enabled and section.content.strip()],
        key=lambda section: (section.priority, section.name),
    )
