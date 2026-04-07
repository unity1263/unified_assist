from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from unified_assist.tools.base import ToolResult
from unified_assist.utils.paths import ensure_dir


class ToolResultStore:
    def __init__(self, root_dir: str | Path, max_inline_chars: int = 800) -> None:
        self.root_dir = ensure_dir(root_dir)
        self.max_inline_chars = max_inline_chars

    def persist_if_needed(self, tool_name: str, tool_use_id: str, result: ToolResult) -> ToolResult:
        if len(result.content) <= self.max_inline_chars:
            return result

        target = self.root_dir / f"{tool_use_id}_{tool_name}.json"
        payload = {
            "tool_name": tool_name,
            "content": result.content,
            "data": result.data,
            "metadata": result.metadata,
        }
        target.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        preview = result.content[: self.max_inline_chars].rstrip()
        preview += f"\n\n[full output persisted to {target}]"
        metadata = dict(result.metadata)
        metadata["persisted_path"] = str(target)
        metadata["truncated"] = True
        return replace(result, content=preview, metadata=metadata)
