from __future__ import annotations

from unified_assist.memory.manager import MemoryManager
from unified_assist.memory.store import MemoryStore


def rebuild_memory_index(store: MemoryStore) -> str:
    manager = MemoryManager(store)
    manager.prepare()
    return manager.rebuild_digests()["workspace"]


def consolidate_memory(manager: MemoryManager) -> dict[str, dict[str, int]]:
    result = manager.consolidate()
    manager.rebuild_digests()
    return result
