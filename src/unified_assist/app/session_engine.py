from __future__ import annotations

from unified_assist.agents.registry import AgentRegistry
from unified_assist.app.app_config import AppConfig
from unified_assist.loop.agent_loop import AgentLoop
from unified_assist.loop.state import LoopState
from unified_assist.messages.models import ProgressMessage, UserMessage
from unified_assist.runtime.services import RuntimeServices
from unified_assist.stability.query_guard import QueryGuard
from unified_assist.stability.resume import repair_messages
from unified_assist.stability.transcript_store import TranscriptStore


class SessionEngine:
    def __init__(
        self,
        *,
        config: AppConfig,
        agent_loop: AgentLoop,
        transcript_store: TranscriptStore,
        agent_registry: AgentRegistry | None = None,
    ) -> None:
        self.config = config
        self.agent_loop = agent_loop
        self.transcript_store = transcript_store
        self.guard = QueryGuard()
        self.messages = []
        self.config.ensure_directories()
        services = RuntimeServices(
            model=self.agent_loop.model,
            prompt_builder=self.agent_loop.prompt_builder,
            tool_executor=self.agent_loop.tool_executor,
            memory_manager=self.agent_loop.memory_manager,
            skills=list(self.agent_loop.skills),
            transcript_store=self.transcript_store,
            agent_registry=agent_registry or AgentRegistry.with_builtins(),
            token_budget=self.agent_loop.token_budget,
        )
        self.agent_loop.tool_context.metadata.setdefault("runtime_services", services)
        self.agent_loop.tool_context.metadata.setdefault("tool_registry", self.agent_loop.tool_executor.registry)
        self.agent_loop.tool_context.metadata.setdefault(
            "skill_catalog",
            {skill.name: skill for skill in self.agent_loop.skills},
        )
        self.agent_loop.tool_context.metadata.setdefault("invoked_skills", [])

    async def submit(self, prompt: str, touched_paths: tuple[str, ...] = ()) -> LoopState:
        if not self.guard.reserve():
            raise RuntimeError("query already running")
        user_message = UserMessage(content=prompt)
        previous_len = len(self.messages)
        reservation_id = self.transcript_store.reserve_turn(self.config.session_id, user_message)
        generation = self.guard.try_start()
        if generation is None:
            self.transcript_store.cancel_turn(self.config.session_id, reservation_id)
            self.guard.cancel_reservation()
            raise RuntimeError("query already running")

        try:
            state = await self.agent_loop.run([*self.messages, user_message], touched_paths=touched_paths)
            new_messages = state.messages[previous_len + 1 :]
            self.transcript_store.commit_turn(self.config.session_id, reservation_id, new_messages)
            self.messages = state.messages
            if self.agent_loop.memory_manager is not None:
                try:
                    result = self.agent_loop.memory_manager.capture_turn(
                        [user_message, *new_messages],
                        active_workspace=str(self.config.root_dir),
                        touched_paths=touched_paths,
                        session_id=self.config.session_id,
                    )
                    if result.pending_confirmations:
                        pending_titles = ", ".join(item.title for item in result.pending_confirmations[:2])
                        note = ProgressMessage(
                            content=(
                                "Held memory candidates for confirmation instead of saving them as durable facts: "
                                f"{pending_titles}"
                            ),
                            stage="memory_pending_confirmation",
                        )
                        state.messages.append(note)
                        self.messages = state.messages
                        self.transcript_store.append_message(self.config.session_id, note)
                except Exception:
                    pass
            return state
        finally:
            self.guard.end(generation)

    def resume(self) -> list:
        loaded = self.transcript_store.load_transcript(self.config.session_id)
        self.messages = repair_messages(loaded.messages, pending_turns=loaded.pending_turns)
        return self.messages
