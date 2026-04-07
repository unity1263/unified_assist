from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any

from unified_assist.messages.blocks import ToolResultBlock
from unified_assist.messages.models import ToolResultMessage
from unified_assist.runtime.services import RuntimeServices
from unified_assist.skills.hooks import HookOutcome, SkillHookRegistry
from unified_assist.tools.base import ToolCall, ToolContext, ToolResult
from unified_assist.tools.permissions import decide_permission
from unified_assist.tools.registry import ToolRegistry
from unified_assist.tools.result_store import ToolResultStore


@dataclass(frozen=True, slots=True)
class ToolProgressUpdate:
    call: ToolCall
    message: str
    stage: str
    source: str = "executor"
    metadata: dict[str, Any] = field(default_factory=dict)
    type: str = field(init=False, default="progress")


@dataclass(frozen=True, slots=True)
class ToolResultUpdate:
    call: ToolCall
    message: ToolResultMessage
    type: str = field(init=False, default="result")


@dataclass(frozen=True, slots=True)
class ToolContextUpdate:
    call: ToolCall
    metadata: dict[str, Any]
    source: str = "tool"
    type: str = field(init=False, default="context")


ToolExecutionUpdate = ToolProgressUpdate | ToolResultUpdate | ToolContextUpdate


@dataclass(slots=True)
class _PreparedCall:
    call: ToolCall
    parsed_input: object | None
    is_concurrency_safe: bool


@dataclass(slots=True)
class _ExecutionOutcome:
    call: ToolCall
    message: ToolResultMessage
    context_patch: dict[str, Any] = field(default_factory=dict)


class ToolExecutor:
    def __init__(self, registry: ToolRegistry, result_store: ToolResultStore) -> None:
        self.registry = registry
        self.result_store = result_store

    async def execute_calls(
        self, calls: Sequence[ToolCall], context: ToolContext
    ) -> list[ToolResultMessage]:
        results: list[ToolResultMessage] = []
        async for update in self.execute_stream(calls, context):
            if isinstance(update, ToolResultUpdate):
                results.append(update.message)
        return results

    async def execute_stream(
        self,
        calls: Sequence[ToolCall],
        context: ToolContext,
        *,
        hook_registry: SkillHookRegistry | None = None,
    ) -> AsyncIterator[ToolExecutionUpdate]:
        prepared = self._prepare_calls(calls)
        working_context = context.snapshot()
        for batch in self._build_batches(prepared):
            if batch and batch[0].is_concurrency_safe and len(batch) > 1:
                async for update in self._execute_concurrent_batch(
                    batch,
                    working_context,
                    hook_registry=hook_registry,
                ):
                    if isinstance(update, ToolContextUpdate):
                        working_context.merge_metadata(update.metadata)
                    yield update
                continue

            for item in batch:
                async for update in self._execute_stream_one(
                    item,
                    working_context,
                    hook_registry=hook_registry,
                ):
                    if isinstance(update, ToolContextUpdate):
                        working_context.merge_metadata(update.metadata)
                    yield update

    def _prepare_calls(self, calls: Sequence[ToolCall]) -> list[_PreparedCall]:
        prepared: list[_PreparedCall] = []
        for call in calls:
            tool = self.registry.get(call.name)
            if tool is None:
                prepared.append(_PreparedCall(call=call, parsed_input=None, is_concurrency_safe=False))
                continue
            try:
                parsed_input = tool.parse_input(call.input)
            except Exception:
                prepared.append(_PreparedCall(call=call, parsed_input=None, is_concurrency_safe=False))
                continue
            prepared.append(
                _PreparedCall(
                    call=call,
                    parsed_input=parsed_input,
                    is_concurrency_safe=tool.is_concurrency_safe(parsed_input),
                )
            )
        return prepared

    def _build_batches(self, prepared: Sequence[_PreparedCall]) -> list[list[_PreparedCall]]:
        batches: list[list[_PreparedCall]] = []
        for item in prepared:
            if item.is_concurrency_safe and batches and all(existing.is_concurrency_safe for existing in batches[-1]):
                batches[-1].append(item)
            else:
                batches.append([item])
        return batches

    async def _execute_concurrent_batch(
        self,
        batch: Sequence[_PreparedCall],
        context: ToolContext,
        *,
        hook_registry: SkillHookRegistry | None,
    ) -> AsyncIterator[ToolExecutionUpdate]:
        tasks: list[asyncio.Task[tuple[_ExecutionOutcome, ToolContext]]] = []
        for item in batch:
            call_context = context.snapshot(
                metadata_updates={
                    "current_tool": item.call.name,
                    "current_tool_use_id": item.call.tool_use_id,
                }
            )
            async for update in self._emit_pre_execution_updates(
                item,
                call_context,
                hook_registry=hook_registry,
            ):
                yield update
            tasks.append(asyncio.create_task(self._execute_with_context(item, call_context)))

        for task in asyncio.as_completed(tasks):
            outcome, call_context = await task
            async for update in self._emit_post_execution_updates(
                outcome,
                call_context,
                hook_registry=hook_registry,
            ):
                yield update

    async def _execute_stream_one(
        self,
        item: _PreparedCall,
        context: ToolContext,
        *,
        hook_registry: SkillHookRegistry | None,
    ) -> AsyncIterator[ToolExecutionUpdate]:
        call_context = context.snapshot(
            metadata_updates={
                "current_tool": item.call.name,
                "current_tool_use_id": item.call.tool_use_id,
            }
        )
        async for update in self._emit_pre_execution_updates(
            item,
            call_context,
            hook_registry=hook_registry,
        ):
            yield update
        outcome = await self._execute_one(item, call_context)
        async for update in self._emit_post_execution_updates(
            outcome,
            call_context,
            hook_registry=hook_registry,
        ):
            yield update

    async def _emit_pre_execution_updates(
        self,
        item: _PreparedCall,
        context: ToolContext,
        *,
        hook_registry: SkillHookRegistry | None,
    ) -> AsyncIterator[ToolExecutionUpdate]:
        tool = self.registry.get(item.call.name)
        description = tool.describe_call(item.parsed_input) if tool and item.parsed_input is not None else item.call.name
        self._emit_runtime_event(
            context,
            "tool_started",
            tool_name=item.call.name,
            tool_use_id=item.call.tool_use_id,
        )
        yield ToolProgressUpdate(
            call=item.call,
            message=f"Running {item.call.name}: {description}",
            stage="tool_started",
        )
        async for update in self._run_hooks(
            event="pre_tool",
            call=item.call,
            context=context,
            hook_registry=hook_registry,
        ):
            yield update

    async def _emit_post_execution_updates(
        self,
        outcome: _ExecutionOutcome,
        context: ToolContext,
        *,
        hook_registry: SkillHookRegistry | None,
    ) -> AsyncIterator[ToolExecutionUpdate]:
        if outcome.context_patch:
            yield ToolContextUpdate(call=outcome.call, metadata=outcome.context_patch)
        async for update in self._run_hooks(
            event="post_tool",
            call=outcome.call,
            context=context,
            hook_registry=hook_registry,
            result_message=outcome.message,
        ):
            yield update
        self._emit_runtime_event(
            context,
            "tool_completed",
            tool_name=outcome.call.name,
            tool_use_id=outcome.call.tool_use_id,
            is_error=outcome.message.results[0].is_error if outcome.message.results else False,
        )
        yield ToolResultUpdate(call=outcome.call, message=outcome.message)

    async def _run_hooks(
        self,
        *,
        event: str,
        call: ToolCall,
        context: ToolContext,
        hook_registry: SkillHookRegistry | None,
        result_message: ToolResultMessage | None = None,
    ) -> AsyncIterator[ToolExecutionUpdate]:
        if hook_registry is None:
            return
        payload = {
            "call": call,
            "context": context,
            "result_message": result_message,
        }
        for output in hook_registry.run(event, payload):
            for outcome in self._normalize_hook_output(output, event):
                self._emit_runtime_event(
                    context,
                    "tool_hook_fired",
                    event=event,
                    tool_name=call.name,
                    tool_use_id=call.tool_use_id,
                    source=outcome.source,
                )
                if outcome.message:
                    yield ToolProgressUpdate(
                        call=call,
                        message=outcome.message,
                        stage=outcome.stage or event,
                        source=outcome.source,
                    )
                if outcome.metadata_updates:
                    yield ToolContextUpdate(
                        call=call,
                        metadata=outcome.metadata_updates,
                        source=outcome.source,
                    )

    def _normalize_hook_output(self, output: Any, event: str) -> list[HookOutcome]:
        if output is None:
            return []
        if isinstance(output, HookOutcome):
            return [output]
        if isinstance(output, str):
            text = output.strip()
            return [HookOutcome(message=text, stage=event)] if text else []
        if isinstance(output, dict):
            message = str(output.get("message", "")).strip()
            metadata_updates = output.get("metadata_updates", {}) or {}
            if not isinstance(metadata_updates, dict):
                metadata_updates = {}
            if not message and not metadata_updates:
                return []
            return [
                HookOutcome(
                    message=message,
                    metadata_updates=dict(metadata_updates),
                    stage=str(output.get("stage", event)),
                    source=str(output.get("source", "hook")),
                )
            ]
        return []

    async def _execute_one(self, item: _PreparedCall, context: ToolContext) -> _ExecutionOutcome:
        call = item.call
        tool = self.registry.get(call.name)
        if tool is None:
            return _ExecutionOutcome(
                call=call,
                message=self._error_message(call, f"unknown tool: {call.name}"),
            )
        if item.parsed_input is None:
            return _ExecutionOutcome(
                call=call,
                message=self._error_message(call, "invalid tool input"),
            )

        validation = await tool.validate(item.parsed_input, context)
        if not validation.ok:
            return _ExecutionOutcome(call=call, message=self._error_message(call, validation.message))

        permission = await tool.check_permission(item.parsed_input, context)
        if permission.behavior == "ask":
            return _ExecutionOutcome(
                call=call,
                message=self._error_message(
                    call,
                    permission.reason or "tool use requires permission",
                    metadata={
                        "needs_permission": True,
                        "permission_behavior": "ask",
                        "permission_reason": permission.reason,
                    },
                ),
            )
        if permission.behavior != "allow":
            return _ExecutionOutcome(
                call=call,
                message=self._error_message(call, permission.reason or "tool use rejected"),
            )

        default_permission = decide_permission(
            context.permission_mode,
            is_read_only=tool.is_read_only(item.parsed_input),
        )
        if default_permission.behavior != "allow":
            return _ExecutionOutcome(
                call=call,
                message=self._error_message(
                    call,
                    default_permission.reason,
                    metadata={
                        "needs_permission": default_permission.behavior == "ask",
                        "permission_behavior": default_permission.behavior,
                        "permission_reason": default_permission.reason,
                    },
                ),
            )

        result = await tool.call(item.parsed_input, context)
        persisted = self.result_store.persist_if_needed(tool.name, call.tool_use_id, result)
        context_patch = persisted.metadata.get("context_patch", {}) or {}
        if not isinstance(context_patch, dict):
            context_patch = {}
        return _ExecutionOutcome(
            call=call,
            message=ToolResultMessage(
                results=[
                    ToolResultBlock(
                        tool_use_id=call.tool_use_id,
                        content=persisted.content,
                        is_error=persisted.is_error,
                    )
                ],
                source_tool=tool.name,
                metadata=persisted.metadata,
            ),
            context_patch=dict(context_patch),
        )

    async def _execute_with_context(
        self, item: _PreparedCall, context: ToolContext
    ) -> tuple[_ExecutionOutcome, ToolContext]:
        return await self._execute_one(item, context), context

    def _error_message(
        self,
        call: ToolCall,
        message: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResultMessage:
        return ToolResultMessage(
            results=[ToolResultBlock(tool_use_id=call.tool_use_id, content=message, is_error=True)],
            source_tool=call.name,
            metadata=dict(metadata or {}),
        )

    def _emit_runtime_event(self, context: ToolContext, kind: str, **payload: Any) -> None:
        services = context.metadata.get("runtime_services")
        if isinstance(services, RuntimeServices):
            services.event_bus.emit(kind, **payload)
