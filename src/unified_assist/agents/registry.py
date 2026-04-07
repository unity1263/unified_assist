from __future__ import annotations

from dataclasses import dataclass, field

from unified_assist.agents.definitions import AgentDefinition, GENERAL_PURPOSE_AGENT, builtin_agents


@dataclass(slots=True)
class AgentRegistry:
    _agents: dict[str, AgentDefinition] = field(default_factory=dict)

    @classmethod
    def with_builtins(cls) -> "AgentRegistry":
        registry = cls()
        for agent in builtin_agents():
            registry.register(agent)
        return registry

    def register(self, agent: AgentDefinition) -> None:
        self._agents[agent.agent_type] = agent

    def resolve(self, agent_type: str | None) -> AgentDefinition:
        if not agent_type:
            return self._agents.get(GENERAL_PURPOSE_AGENT.agent_type, GENERAL_PURPOSE_AGENT)
        if agent_type not in self._agents:
            raise KeyError(f"unknown agent type: {agent_type}")
        return self._agents[agent_type]

    def list_agent_types(self) -> list[str]:
        return sorted(self._agents)
