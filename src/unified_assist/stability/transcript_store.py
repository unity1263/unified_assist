from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from unified_assist.messages.models import Message, message_from_dict, message_to_dict
from unified_assist.utils.paths import ensure_dir


@dataclass(frozen=True, slots=True)
class PendingTranscriptTurn:
    reservation_id: str
    message: Message


@dataclass(frozen=True, slots=True)
class TranscriptLoadResult:
    messages: list[Message]
    pending_turns: list[PendingTranscriptTurn]


class TranscriptStore:
    def __init__(self, root_dir: str | Path) -> None:
        self.root_dir = ensure_dir(root_dir)

    def session_path(self, session_id: str) -> Path:
        return self.root_dir / f"{session_id}.jsonl"

    def append_message(self, session_id: str, message: Message) -> None:
        self._append_record(
            session_id,
            {
                "record_type": "message",
                "message": message_to_dict(message),
            },
        )

    def append_messages(self, session_id: str, messages: list[Message]) -> None:
        for message in messages:
            self.append_message(session_id, message)

    def load_messages(self, session_id: str) -> list[Message]:
        return self.load_transcript(session_id).messages

    def reserve_turn(self, session_id: str, message: Message) -> str:
        reservation_id = uuid4().hex
        self._append_record(
            session_id,
            {
                "record_type": "pending_turn",
                "reservation_id": reservation_id,
                "message": message_to_dict(message),
            },
        )
        return reservation_id

    def commit_turn(
        self, session_id: str, reservation_id: str, messages: list[Message]
    ) -> None:
        self._append_record(
            session_id,
            {
                "record_type": "commit_turn",
                "reservation_id": reservation_id,
                "messages": [message_to_dict(message) for message in messages],
            },
        )

    def cancel_turn(self, session_id: str, reservation_id: str) -> None:
        self._append_record(
            session_id,
            {
                "record_type": "cancel_turn",
                "reservation_id": reservation_id,
            },
        )

    def load_transcript(self, session_id: str) -> TranscriptLoadResult:
        path = self.session_path(session_id)
        if not path.exists():
            return TranscriptLoadResult(messages=[], pending_turns=[])
        messages: list[Message] = []
        pending: dict[str, Message] = {}
        pending_order: list[str] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                record_type = record.get("record_type", "message")
                if record_type == "message":
                    payload = record.get("message", record)
                    messages.append(message_from_dict(payload))
                elif record_type == "pending_turn":
                    reservation_id = str(record["reservation_id"])
                    pending[reservation_id] = message_from_dict(record["message"])
                    if reservation_id not in pending_order:
                        pending_order.append(reservation_id)
                elif record_type == "commit_turn":
                    reservation_id = str(record["reservation_id"])
                    pending_message = pending.pop(reservation_id, None)
                    if reservation_id in pending_order:
                        pending_order.remove(reservation_id)
                    if pending_message is not None:
                        messages.append(pending_message)
                    messages.extend(
                        message_from_dict(item) for item in record.get("messages", [])
                    )
                elif record_type == "cancel_turn":
                    reservation_id = str(record["reservation_id"])
                    pending.pop(reservation_id, None)
                    if reservation_id in pending_order:
                        pending_order.remove(reservation_id)
        return TranscriptLoadResult(
            messages=messages,
            pending_turns=[
                PendingTranscriptTurn(reservation_id=reservation_id, message=pending[reservation_id])
                for reservation_id in pending_order
                if reservation_id in pending
            ],
        )

    def _append_record(self, session_id: str, record: dict[str, object]) -> None:
        path = self.session_path(session_id)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")
