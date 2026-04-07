from __future__ import annotations


class QueryGuard:
    def __init__(self) -> None:
        self._status = "idle"
        self._generation = 0

    @property
    def is_active(self) -> bool:
        return self._status != "idle"

    @property
    def generation(self) -> int:
        return self._generation

    def reserve(self) -> bool:
        if self._status != "idle":
            return False
        self._status = "dispatching"
        return True

    def cancel_reservation(self) -> None:
        if self._status == "dispatching":
            self._status = "idle"

    def try_start(self) -> int | None:
        if self._status == "running":
            return None
        self._status = "running"
        self._generation += 1
        return self._generation

    def end(self, generation: int) -> bool:
        if generation != self._generation or self._status != "running":
            return False
        self._status = "idle"
        return True

    def force_end(self) -> None:
        if self._status == "idle":
            return
        self._status = "idle"
        self._generation += 1
