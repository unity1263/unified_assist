from __future__ import annotations

from dataclasses import dataclass

from unified_assist.messages.models import AssistantMessage, Message, SystemMessage, ToolResultMessage, UserMessage


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def message_tokens(message: Message) -> int:
    if isinstance(message, UserMessage):
        return estimate_tokens(message.content)
    if isinstance(message, AssistantMessage):
        return estimate_tokens(message.text)
    if isinstance(message, ToolResultMessage):
        return sum(estimate_tokens(result.content) for result in message.results)
    if isinstance(message, SystemMessage):
        return estimate_tokens(message.content)
    return estimate_tokens(str(message))


def conversation_tokens(messages: list[Message]) -> int:
    return sum(message_tokens(message) for message in messages)


@dataclass(frozen=True, slots=True)
class BudgetDecision:
    action: str
    message: str = ""


@dataclass(slots=True)
class TokenBudget:
    total_tokens: int
    continue_ratio: float = 0.85

    def decide(self, messages: list[Message]) -> BudgetDecision:
        used = conversation_tokens(messages)
        if used >= self.total_tokens:
            return BudgetDecision("stop", "Token budget exhausted")
        if used >= int(self.total_tokens * self.continue_ratio):
            return BudgetDecision(
                "continue",
                "Token budget is getting tight. Continue only with the remaining essential work.",
            )
        return BudgetDecision("ok")
