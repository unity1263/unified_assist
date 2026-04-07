from __future__ import annotations

from unified_assist.messages.models import AttachmentMessage


def build_agent_attachment(*, agent_name: str, transition_reason: str, summary: str) -> AttachmentMessage:
    return AttachmentMessage(
        kind="agent_result",
        data={
            "agent_name": agent_name,
            "transition_reason": transition_reason,
            "summary": summary,
        },
    )
