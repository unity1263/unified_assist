from __future__ import annotations

from unified_assist.messages.models import Message, UserMessage


FORK_MARKER = "[forked-agent-context]"


def build_fork_messages(parent_messages: list[Message], directive: str) -> list[Message]:
    inherited = list(parent_messages)
    inherited.append(
        UserMessage(
            content=(
                f"{FORK_MARKER}\n"
                "You are operating as a forked child agent. Stay within your assigned scope and return only the delegated result.\n\n"
                f"Directive: {directive}"
            ),
            is_meta=True,
        )
    )
    return inherited


def is_fork_child(messages: list[Message]) -> bool:
    return any(
        isinstance(message, UserMessage) and FORK_MARKER in message.content
        for message in messages
    )
