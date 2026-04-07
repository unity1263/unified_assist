from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    agent_type: str
    description: str
    system_prompt: str
    allowed_tools: list[str] | None = None
    max_turns: int = 6
    include_parent_context: bool = False
    model: str | None = None
    allow_nested_agents: bool = False


GENERAL_PURPOSE_AGENT = AgentDefinition(
    agent_type="general-purpose",
    description="General coding and problem-solving agent",
    system_prompt=(
        "You are a focused subagent. Complete the delegated task directly, use tools when needed, "
        "and return a concise result for the parent agent."
    ),
    allowed_tools=None,
    max_turns=6,
    include_parent_context=False,
    allow_nested_agents=False,
)

RESEARCH_AGENT = AgentDefinition(
    agent_type="researcher",
    description="Investigate code and return findings",
    system_prompt=(
        "You are a research-focused subagent. Read code, search precisely, and return scoped findings."
    ),
    allowed_tools=["read_file", "glob_search", "bash", "think", "ask_user"],
    max_turns=5,
    include_parent_context=True,
    allow_nested_agents=False,
)

PLANNER_AGENT = AgentDefinition(
    agent_type="planner",
    description="Break down work into a concrete execution plan",
    system_prompt=(
        "You are a planning subagent. Analyze the task and return an actionable, ordered plan."
    ),
    allowed_tools=["read_file", "glob_search", "think", "ask_user"],
    max_turns=4,
    include_parent_context=True,
    allow_nested_agents=False,
)

REVIEW_AGENT = AgentDefinition(
    agent_type="reviewer",
    description="Review changes and identify risks",
    system_prompt=(
        "You are a review subagent. Focus on bugs, regressions, and missing tests."
    ),
    allowed_tools=["read_file", "glob_search", "bash", "think"],
    max_turns=5,
    include_parent_context=True,
    allow_nested_agents=False,
)


def builtin_agents() -> list[AgentDefinition]:
    return [GENERAL_PURPOSE_AGENT, RESEARCH_AGENT, PLANNER_AGENT, REVIEW_AGENT]
