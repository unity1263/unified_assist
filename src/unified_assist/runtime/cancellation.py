from __future__ import annotations

import asyncio


class CancellationScope:
    def __init__(self, parent: "CancellationScope | None" = None) -> None:
        self._event = asyncio.Event()
        self._children: list[CancellationScope] = []
        self.parent = parent
        if parent is not None:
            parent._children.append(self)

    @property
    def cancelled(self) -> bool:
        return self._event.is_set() or (self.parent.cancelled if self.parent is not None else False)

    def cancel(self) -> None:
        self._event.set()
        for child in list(self._children):
            child.cancel()

    def child(self) -> "CancellationScope":
        return CancellationScope(parent=self)
