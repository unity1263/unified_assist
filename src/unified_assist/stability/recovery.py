from __future__ import annotations

from dataclasses import dataclass

from unified_assist.messages.models import AssistantMessage, UserMessage


@dataclass(slots=True)
class RecoveryAction:
    should_retry: bool
    retry_message: UserMessage | None = None
    reason: str = "none"
    should_compact: bool = False


def maybe_recover(assistant_message: AssistantMessage, recovery_count: int) -> RecoveryAction:
    if not assistant_message.is_error:
        return RecoveryAction(False)

    text = assistant_message.text.lower()
    if "max_output_tokens" in text and recovery_count < 2:
        return RecoveryAction(
            should_retry=True,
            retry_message=UserMessage(
                content=(
                    "Output token limit hit. Resume directly from where you left off and finish the remaining work."
                ),
                is_meta=True,
            ),
            reason="max_output_tokens",
            should_compact=False,
        )
    if "prompt too long" in text and recovery_count < 1:
        return RecoveryAction(
            should_retry=True,
            retry_message=UserMessage(
                content=(
                    "Context overflow detected. Continue with a tighter summary of prior work and focus only on the remaining steps."
                ),
                is_meta=True,
            ),
            reason="prompt_too_long",
            should_compact=True,
        )
    return RecoveryAction(False)
