from __future__ import annotations

from typing import Iterable

from unified_assist.messages.models import AssistantMessage, Message, UserMessage, message_from_dict, message_to_dict


def serialize_messages(messages: Iterable[Message]) -> list[dict]:
    return [message_to_dict(message) for message in messages]


def deserialize_messages(items: Iterable[dict]) -> list[Message]:
    return [message_from_dict(item) for item in items]


def drop_empty_assistant_messages(messages: Iterable[Message]) -> list[Message]:
    output: list[Message] = []
    for message in messages:
        if isinstance(message, AssistantMessage) and not message.blocks:
            continue
        if isinstance(message, AssistantMessage) and not message.text and not message.tool_uses:
            continue
        output.append(message)
    return output


def last_user_text(messages: Iterable[Message]) -> str:
    for message in reversed(list(messages)):
        if isinstance(message, UserMessage) and not message.is_meta:
            return message.content
    return ""
