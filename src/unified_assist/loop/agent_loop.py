from __future__ import annotations

from collections.abc import Sequence
import re

from unified_assist.llm.base import (
    AssistantDeltaEvent,
    AssistantErrorEvent,
    AssistantMessageStartEvent,
    AssistantMessageStopEvent,
    AssistantToolUseEvent,
    GenerationRequest,
    ModelAdapter,
)
from unified_assist.loop.state import LoopState
from unified_assist.loop.transitions import append_turn
from unified_assist.messages.blocks import ThinkingBlock
from unified_assist.memory.manager import MemoryManager
from unified_assist.memory.types import RecallContext, utc_now
from unified_assist.messages.blocks import TextBlock, ToolUseBlock
from unified_assist.messages.models import AssistantMessage, ProgressMessage, ToolResultMessage, UserMessage
from unified_assist.messages.normalize import last_user_text
from unified_assist.prompt.builder import PromptBuilder
from unified_assist.skills.hooks import build_skill_hook_registry
from unified_assist.skills.models import Skill
from unified_assist.skills.resolver import resolve_active_skills
from unified_assist.stability.compaction import compact_messages
from unified_assist.stability.recovery import maybe_recover
from unified_assist.stability.token_budget import TokenBudget
from unified_assist.tools.base import ToolCall, ToolContext
from unified_assist.tools.executor import ToolContextUpdate, ToolExecutor, ToolProgressUpdate, ToolResultUpdate


class AgentLoop:
    def __init__(
        self,
        *,
        model: ModelAdapter,
        prompt_builder: PromptBuilder,
        tool_executor: ToolExecutor,
        tool_context: ToolContext,
        memory_manager: MemoryManager | None = None,
        skills: Sequence[Skill] | None = None,
        max_turns: int = 8,
        compaction_limit: int = 12,
        token_budget: TokenBudget | None = None,
    ) -> None:
        self.model = model
        self.prompt_builder = prompt_builder
        self.tool_executor = tool_executor
        self.tool_context = tool_context
        self.memory_manager = memory_manager
        self.skills = list(skills or [])
        self.max_turns = max_turns
        self.compaction_limit = compaction_limit
        self.token_budget = token_budget

    async def run(self, messages: list, touched_paths: Sequence[str] = ()) -> LoopState:
        state = LoopState(messages=list(messages))

        while True:
            state.messages = compact_messages(state.messages, max_messages=self.compaction_limit)
            query = last_user_text(state.messages)
            active_skills = resolve_active_skills(
                self.skills,
                touched_paths,
                invoked_skill_names=self._invoked_skill_names(),
            )
            hook_registry = build_skill_hook_registry(active_skills)
            recall_context = self._build_recall_context(query, touched_paths=touched_paths)
            recalled_memories = self.memory_manager.recall(recall_context) if self.memory_manager else []
            preferred_tools_by_skill = {
                skill.name: list(skill.allowed_tools)
                for skill in active_skills
                if skill.allowed_tools
            }
            memory_instruction = (
                self.memory_manager.memory_instruction_block() if self.memory_manager else ""
            )
            prompt = self.prompt_builder.build(
                self.prompt_builder.default_sections(
                    env_info=f"Working directory: {self.tool_context.cwd}",
                    active_skills=active_skills,
                    memory_instruction=memory_instruction,
                    recalled_memories=recalled_memories,
                    session_guidance=self._build_session_guidance(),
                    output_style="Prefer concise, direct answers grounded in tool results.",
                )
            )

            assistant_message = await self._stream_assistant_turn(
                GenerationRequest(
                    system_prompt=prompt,
                    messages=list(state.messages),
                    tools=self.tool_executor.registry.tool_specs(),
                    metadata={"turn": state.turn_count},
                )
            )

            tool_calls = [
                ToolCall(
                    name=block.name,
                    input=block.input,
                    tool_use_id=block.tool_use_id,
                )
                for block in assistant_message.blocks
                if isinstance(block, ToolUseBlock)
            ]

            if not tool_calls:
                state.messages.append(assistant_message)
                recovery = maybe_recover(
                    assistant_message, state.max_output_recovery_count
                )
                if recovery.should_retry and recovery.retry_message is not None:
                    if recovery.should_compact and not state.reactive_compaction_attempted:
                        state.messages = compact_messages(
                            state.messages,
                            max_messages=max(6, self.compaction_limit // 2),
                            preserve_tail=2,
                        )
                        state.reactive_compaction_attempted = True
                    state.messages.append(recovery.retry_message)
                    state.max_output_recovery_count += 1
                    state.transition_reason = recovery.reason
                    continue

                if self.token_budget is not None:
                    decision = self.token_budget.decide(state.messages)
                    if decision.action == "continue":
                        state.messages.append(UserMessage(content=decision.message, is_meta=True))
                        state.transition_reason = "token_budget_continue"
                        continue
                    if decision.action == "stop":
                        state.transition_reason = "token_budget_stop"
                        return state

                state.transition_reason = "completed"
                return state

            turn_context = self.tool_context.snapshot(
                metadata_updates={
                    "messages": list(state.messages),
                    "active_skills": [skill.name for skill in active_skills],
                    "active_skill_tools": preferred_tools_by_skill,
                    "skill_catalog": {skill.name: skill for skill in self.skills},
                    "recalled_memories": [
                        {
                            "name": item.entry.name,
                            "kind": item.entry.kind,
                            "scope": item.entry.scope,
                            "freshness": item.freshness,
                            "freshness_note": item.freshness_note,
                        }
                        for item in recalled_memories
                    ],
                }
            )
            tool_results: list[ToolResultMessage] = []
            intermediate_messages: list[ProgressMessage] = []
            async for update in self.tool_executor.execute_stream(
                tool_calls,
                turn_context,
                hook_registry=hook_registry,
            ):
                if isinstance(update, ToolProgressUpdate):
                    intermediate_messages.append(
                        ProgressMessage(content=update.message, stage=update.stage)
                    )
                elif isinstance(update, ToolContextUpdate):
                    self.tool_context.merge_metadata(update.metadata)
                    turn_context.merge_metadata(update.metadata)
                elif isinstance(update, ToolResultUpdate):
                    tool_results.append(update.message)
            state = append_turn(
                state,
                assistant_message=assistant_message,
                tool_results=tool_results,
                intermediate_messages=intermediate_messages,
            )

            if any(result.metadata.get("needs_user_input") for result in tool_results):
                state.transition_reason = "needs_user_input"
                return state

            if any(result.metadata.get("needs_permission") for result in tool_results):
                state.transition_reason = "needs_permission"
                return state

            if state.turn_count > self.max_turns:
                state.transition_reason = "max_turns"
                return state

    async def _stream_assistant_turn(self, request: GenerationRequest) -> AssistantMessage:
        blocks: list[TextBlock | ThinkingBlock | ToolUseBlock] = []
        stop_reason: str | None = None
        is_error = False
        phase = "awaiting_start"

        async for event in self.model.stream_generate(request):
            if isinstance(event, AssistantMessageStartEvent):
                phase = "streaming"
                continue

            if phase == "stopped":
                raise RuntimeError("received assistant event after stop")

            if isinstance(event, AssistantDeltaEvent):
                phase = "streaming"
                self._append_delta_block(blocks, event.block_type, event.delta)
                continue

            if isinstance(event, AssistantToolUseEvent):
                phase = "streaming"
                blocks.append(
                    ToolUseBlock(
                        name=event.name,
                        input=dict(event.input),
                        tool_use_id=event.tool_use_id,
                    )
                )
                continue

            if isinstance(event, AssistantErrorEvent):
                phase = "streaming"
                is_error = True
                self._append_delta_block(blocks, "text", event.message)
                stop_reason = event.stop_reason
                continue

            if isinstance(event, AssistantMessageStopEvent):
                phase = "stopped"
                stop_reason = event.stop_reason

        return AssistantMessage(
            blocks=blocks,
            stop_reason=stop_reason,
            is_error=is_error,
        )

    def _append_delta_block(
        self,
        blocks: list[TextBlock | ThinkingBlock | ToolUseBlock],
        block_type: str,
        delta: str,
    ) -> None:
        if not delta:
            return
        if block_type == "thinking":
            if blocks and isinstance(blocks[-1], ThinkingBlock):
                blocks[-1] = ThinkingBlock(text=blocks[-1].text + delta)
                return
            blocks.append(ThinkingBlock(text=delta))
            return
        if blocks and isinstance(blocks[-1], TextBlock):
            blocks[-1] = TextBlock(text=blocks[-1].text + delta)
            return
        blocks.append(TextBlock(text=delta))

    def _invoked_skill_names(self) -> list[str]:
        names = self.tool_context.metadata.get("invoked_skills", [])
        if not isinstance(names, list):
            return []
        return [str(name) for name in names if str(name).strip()]

    def _build_session_guidance(self) -> str:
        parts = [
            "Use tools for actions and observed facts.",
            "When recalled memory includes a verification note, verify it before treating it as current fact.",
        ]
        todos = self.tool_context.metadata.get("todos", [])
        if isinstance(todos, list) and todos:
            lines = ["Current todo list:"]
            for item in todos:
                if not isinstance(item, dict):
                    continue
                status = str(item.get("status", "pending"))
                content = str(item.get("content", "")).strip()
                if content:
                    lines.append(f"- [{status}] {content}")
            if len(lines) > 1:
                parts.append("\n".join(lines))
        return "\n".join(parts)

    def _build_recall_context(self, query: str, *, touched_paths: Sequence[str]) -> RecallContext:
        return RecallContext(
            query=query,
            active_workspace=str(self.tool_context.cwd),
            participants=tuple(self._participants_from_query(query)),
            current_time=utc_now(),
            todos=tuple(self._current_todo_items()),
            touched_paths=tuple(str(path) for path in touched_paths),
            source_hints=tuple(self._source_hints(touched_paths)),
            allowed_scopes=("private", "workspace"),
        )

    def _participants_from_query(self, query: str) -> list[str]:
        return [
            match.group(0)
            for match in re.finditer(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?\b", query)
        ]

    def _current_todo_items(self) -> list[str]:
        todos = self.tool_context.metadata.get("todos", [])
        if not isinstance(todos, list):
            return []
        items: list[str] = []
        for item in todos:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "")).strip()
            if content:
                items.append(content)
        return items

    def _source_hints(self, touched_paths: Sequence[str]) -> list[str]:
        return [str(path).split("/")[-1] for path in touched_paths]
