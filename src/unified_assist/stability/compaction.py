from __future__ import annotations

from unified_assist.messages.models import (
    AssistantMessage,
    AttachmentMessage,
    Message,
    ProgressMessage,
    SystemMessage,
    ToolResultMessage,
    UserMessage,
)


def _message_summary(message: Message) -> str:
    if isinstance(message, UserMessage):
        return f"user: {message.content[:80]}"
    if isinstance(message, AssistantMessage):
        return f"assistant: {message.text[:80]}"
    if isinstance(message, ToolResultMessage):
        text = " | ".join(result.content[:40] for result in message.results)
        return f"tool_result: {text}"
    if isinstance(message, SystemMessage):
        return f"system: {message.content[:80]}"
    if isinstance(message, ProgressMessage):
        return f"progress: {message.content[:80]}"
    if isinstance(message, AttachmentMessage):
        if message.kind == "compaction_boundary":
            summary = str(message.data.get("summary", "previous summary"))
            return f"compaction_boundary: {summary[:80]}"
        return f"attachment: {message.kind}"
    return getattr(message, "type", "message")


def compact_messages(messages: list[Message], max_messages: int = 12, preserve_tail: int = 4) -> list[Message]:
    if len(messages) <= max_messages:
        return list(messages)

    tail = messages[-preserve_tail:]
    head = messages[:-preserve_tail]
    summary_lines = ["Previous conversation summary:"]
    summary_lines.extend(f"- {_message_summary(message)}" for message in head)
    summary_text = "\n".join(summary_lines)
    boundary = AttachmentMessage(
        kind="compaction_boundary",
        data={
            "original_message_count": len(messages),
            "compacted_count": len(head),
            "preserved_tail_count": len(tail),
            "summary": " | ".join(_message_summary(message) for message in head[:6]),
        },
    )
    return [boundary, SystemMessage(content=summary_text), *tail]
