from __future__ import annotations

from typing import Any

import yaml


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text

    end_marker = "\n---\n"
    end_index = text.find(end_marker, 4)
    if end_index == -1:
        return {}, text

    raw_meta = text[4:end_index]
    body = text[end_index + len(end_marker) :]
    data = yaml.safe_load(raw_meta) or {}
    if not isinstance(data, dict):
        raise ValueError("frontmatter must decode to a mapping")
    return data, body


def dump_frontmatter(metadata: dict[str, Any], body: str) -> str:
    meta = yaml.safe_dump(metadata, sort_keys=False).strip()
    body_text = body.lstrip("\n")
    return f"---\n{meta}\n---\n{body_text}"
