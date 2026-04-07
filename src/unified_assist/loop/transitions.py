from __future__ import annotations

from unified_assist.loop.state import LoopState
from unified_assist.messages.models import AttachmentMessage, AssistantMessage, Message, ToolResultMessage


def append_turn(
    state: LoopState,
    *,
    assistant_message: AssistantMessage,
    tool_results: list[ToolResultMessage],
    intermediate_messages: list[Message] | None = None,
    attachments: list[AttachmentMessage] | None = None,
    reason: str = "next_turn",
) -> LoopState:
    next_messages: list[Message] = list(state.messages)
    next_messages.append(assistant_message)
    next_messages.extend(intermediate_messages or [])
    next_messages.extend(tool_results)
    next_messages.extend(attachments or [])
    return LoopState(
        messages=next_messages,
        turn_count=state.turn_count + 1,
        max_output_recovery_count=state.max_output_recovery_count,
        reactive_compaction_attempted=state.reactive_compaction_attempted,
        transition_reason=reason,
        prompt_cache=dict(state.prompt_cache),
    )
