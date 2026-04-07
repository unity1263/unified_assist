from __future__ import annotations

from unified_assist.messages.models import AssistantMessage, Message, SystemMessage, ToolResultMessage, UserMessage
from unified_assist.messages.normalize import drop_empty_assistant_messages
from unified_assist.stability.transcript_store import PendingTranscriptTurn


def repair_messages(
    messages: list[Message],
    *,
    pending_turns: list[PendingTranscriptTurn] | None = None,
) -> list[Message]:
    pending_turns = pending_turns or []
    resolved_ids = {
        result.tool_use_id
        for message in messages
        if isinstance(message, ToolResultMessage)
        for result in message.results
    }

    repaired: list[Message] = []
    resume_notes: list[SystemMessage] = []
    for message in messages:
        if isinstance(message, AssistantMessage):
            tool_use_ids = {block.tool_use_id for block in message.tool_uses}
            if tool_use_ids and not tool_use_ids.issubset(resolved_ids):
                note = _interrupted_assistant_note(message)
                if note:
                    resume_notes.append(SystemMessage(content=note))
                continue
        repaired.append(message)

    repaired = drop_empty_assistant_messages(repaired)
    if pending_turns:
        for pending in pending_turns:
            repaired.append(pending.message)
            resume_notes.append(
                SystemMessage(
                    content=(
                        "Resume note: The last accepted user turn was recorded but the turn did not complete. "
                        "Continue from that request using the latest stable state."
                    )
                )
            )
    repaired.extend(resume_notes)
    if _should_append_continue_prompt(repaired):
        repaired.append(
            UserMessage(
                content="Continue from the latest stable state and finish any unfinished work.",
                is_meta=True,
            )
        )
    return repaired


def _interrupted_assistant_note(message: AssistantMessage) -> str:
    tool_names = [block.name for block in message.tool_uses]
    parts = [
        "Resume note: A previous assistant turn was interrupted before all tool results were recorded.",
        "Ignore the unfinished tool calls and continue from the latest stable state.",
    ]
    if tool_names:
        parts.append(f"Interrupted tools: {', '.join(tool_names)}.")
    if message.text:
        parts.append(f"Interrupted assistant text: {message.text[:160]}")
    return " ".join(parts).strip()


def _should_append_continue_prompt(messages: list[Message]) -> bool:
    if not messages:
        return False
    last_message = messages[-1]
    if isinstance(last_message, UserMessage):
        return not last_message.is_meta
    if isinstance(last_message, SystemMessage):
        for previous in reversed(messages[:-1]):
            if isinstance(previous, UserMessage):
                return not previous.is_meta
            if isinstance(previous, AssistantMessage):
                return False
        return False
    return False
