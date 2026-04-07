from __future__ import annotations

from dataclasses import dataclass, field

from unified_assist.llm.openai_adapter import OpenAICompatibleAdapter, OpenAIConfig


def _normalize_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    if normalized.endswith("/v1"):
        return f"{normalized}/chat/completions"
    return normalized


@dataclass(slots=True)
class MiniMaxConfig:
    api_key: str = ""
    model: str = "MiniMax-M2.7"
    base_url: str = "https://api.minimaxi.com/v1"
    headers: dict[str, str] = field(default_factory=dict)
    extra_body: dict[str, object] = field(
        default_factory=lambda: {
            "reasoning_split": True,
        }
    )


class MiniMaxAdapter(OpenAICompatibleAdapter):
    def __init__(self, config: MiniMaxConfig) -> None:
        super().__init__(
            OpenAIConfig(
                model=config.model,
                api_key=config.api_key,
                base_url=_normalize_base_url(config.base_url),
                provider_name="minimax",
                headers=dict(config.headers),
                extra_body=dict(config.extra_body),
            )
        )
