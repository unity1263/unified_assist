# Unified Claw Implementation Plan

## 1. Goal

`unified_assist` will be a Python-based super assistant inspired by Claude Code, but not a line-by-line port.

The target is a practical agent runtime with these properties:

- model is only the decision engine, not the whole system
- tools are strongly typed, permissioned, and observable
- skills are modular prompt capabilities, not ad hoc prompt snippets
- memory is file-based, selective, and freshness-aware
- the runtime is resumable, interruptible, and recoverable

## 2. Current assumptions

To keep the first version focused, this design assumes:

- Python `3.12+`
- CLI-first product, TUI/UI later
- single local workspace session first, multi-agent later
- pluggable model backend: OpenAI / Anthropic / compatible API
- first-class coding assistant scenario: read/search/edit/run/plan/remember

## 3. What Claude Code gets right

Based on [arch.md](/home/dehuazhang12/codebase/claude-code-source/arch.md) and the source runtime, the most important architecture to preserve is not the UI, but the runtime shape.

### 3.1 Agent loop

Core idea: `assistant -> tool_use -> tool_result -> assistant -> ...`

Important properties from the source:

- session orchestration is separated from the loop itself
- loop state is explicit, not hidden in recursion
- each turn preprocesses context before calling the model
- loop continuation is based on actual `tool_use` blocks, not only stop reasons
- after tool execution, results are converted back into messages and appended to history
- attachments such as memory and skill discovery are injected between turns

This pattern appears in:

- [src/QueryEngine.ts](/home/dehuazhang12/codebase/claude-code-source/src/QueryEngine.ts#L184)
- [src/query.ts](/home/dehuazhang12/codebase/claude-code-source/src/query.ts#L365)
- [src/query.ts](/home/dehuazhang12/codebase/claude-code-source/src/query.ts#L557)
- [src/query.ts](/home/dehuazhang12/codebase/claude-code-source/src/query.ts#L1378)
- [src/query.ts](/home/dehuazhang12/codebase/claude-code-source/src/query.ts#L1716)

### 3.2 Tool architecture

Claude Code does not let the model call arbitrary runtime functions directly. It routes every tool use through a strict tool contract.

Important properties:

- each tool has input schema
- tool execution has validation before actual call
- permission check is separated from tool logic
- tools declare read-only / destructive / concurrency semantics
- registry decides what tools are visible to the model
- runtime converts all outcomes into standardized `tool_result`

This pattern appears in:

- [src/Tool.ts](/home/dehuazhang12/codebase/claude-code-source/src/Tool.ts#L362)
- [src/Tool.ts](/home/dehuazhang12/codebase/claude-code-source/src/Tool.ts#L750)
- [src/tools.ts](/home/dehuazhang12/codebase/claude-code-source/src/tools.ts#L193)
- [src/services/tools/toolOrchestration.ts](/home/dehuazhang12/codebase/claude-code-source/src/services/tools/toolOrchestration.ts#L20)
- [src/services/tools/toolExecution.ts](/home/dehuazhang12/codebase/claude-code-source/src/services/tools/toolExecution.ts#L615)
- [src/services/tools/StreamingToolExecutor.ts](/home/dehuazhang12/codebase/claude-code-source/src/services/tools/StreamingToolExecutor.ts#L34)

### 3.3 Skill architecture

Claude Code treats skills as managed prompt capabilities with metadata, scope, discovery rules, and hooks.

Important properties:

- skills are loaded from directories, not hardcoded strings
- frontmatter defines usage, arguments, allowed tools, model, execution context
- bundled skills and disk skills use the same conceptual contract
- skills can be discovered dynamically from project paths
- path-conditioned skills activate only when relevant files are touched
- a skill can register hooks into the session lifecycle

This pattern appears in:

- [src/skills/loadSkillsDir.ts](/home/dehuazhang12/codebase/claude-code-source/src/skills/loadSkillsDir.ts#L181)
- [src/skills/loadSkillsDir.ts](/home/dehuazhang12/codebase/claude-code-source/src/skills/loadSkillsDir.ts#L268)
- [src/skills/loadSkillsDir.ts](/home/dehuazhang12/codebase/claude-code-source/src/skills/loadSkillsDir.ts#L628)
- [src/skills/loadSkillsDir.ts](/home/dehuazhang12/codebase/claude-code-source/src/skills/loadSkillsDir.ts#L854)
- [src/skills/loadSkillsDir.ts](/home/dehuazhang12/codebase/claude-code-source/src/skills/loadSkillsDir.ts#L986)
- [src/skills/bundledSkills.ts](/home/dehuazhang12/codebase/claude-code-source/src/skills/bundledSkills.ts#L12)
- [src/utils/hooks/registerSkillHooks.ts](/home/dehuazhang12/codebase/claude-code-source/src/utils/hooks/registerSkillHooks.ts#L8)

### 3.4 Memory architecture

Claude Code's memory is not just vector recall. It is a file-based knowledge system with operating instructions, typed entries, selective recall, and background consolidation.

Important properties:

- memory storage is plain files and markdown, easy to inspect and edit
- memory prompt defines what to save and what not to save
- recall is selective, not "load everything"
- memory entries have freshness/staleness hints
- a background process consolidates memory over time

This pattern appears in:

- [src/memdir/memdir.ts](/home/dehuazhang12/codebase/claude-code-source/src/memdir/memdir.ts#L197)
- [src/memdir/memdir.ts](/home/dehuazhang12/codebase/claude-code-source/src/memdir/memdir.ts#L410)
- [src/memdir/findRelevantMemories.ts](/home/dehuazhang12/codebase/claude-code-source/src/memdir/findRelevantMemories.ts#L32)
- [src/memdir/memoryScan.ts](/home/dehuazhang12/codebase/claude-code-source/src/memdir/memoryScan.ts#L22)
- [src/memdir/memoryAge.ts](/home/dehuazhang12/codebase/claude-code-source/src/memdir/memoryAge.ts#L21)
- [src/services/autoDream/autoDream.ts](/home/dehuazhang12/codebase/claude-code-source/src/services/autoDream/autoDream.ts#L1)

### 3.5 Stability architecture

Claude Code's real moat is stability engineering.

Important properties:

- query lifecycle is guarded against re-entry
- transcript is persisted before and during execution to make resume work
- interrupted or malformed histories are repaired on restore
- token overflow has multiple recovery paths
- max output exhaustion has controlled continuation
- tool execution supports abort, fallback cleanup, and synthetic tool results
- compaction is layered instead of relying on one summarization path

This pattern appears in:

- [src/utils/QueryGuard.ts](/home/dehuazhang12/codebase/claude-code-source/src/utils/QueryGuard.ts#L1)
- [src/QueryEngine.ts](/home/dehuazhang12/codebase/claude-code-source/src/QueryEngine.ts#L442)
- [src/QueryEngine.ts](/home/dehuazhang12/codebase/claude-code-source/src/QueryEngine.ts#L687)
- [src/query.ts](/home/dehuazhang12/codebase/claude-code-source/src/query.ts#L396)
- [src/query.ts](/home/dehuazhang12/codebase/claude-code-source/src/query.ts#L1062)
- [src/query.ts](/home/dehuazhang12/codebase/claude-code-source/src/query.ts#L1185)
- [src/query.ts](/home/dehuazhang12/codebase/claude-code-source/src/query.ts#L1015)
- [src/utils/conversationRecovery.ts](/home/dehuazhang12/codebase/claude-code-source/src/utils/conversationRecovery.ts#L141)
- [src/utils/sessionRestore.ts](/home/dehuazhang12/codebase/claude-code-source/src/utils/sessionRestore.ts#L88)

## 4. Design principles for Unified Claw

The Python project should preserve the architecture, but simplify the first implementation.

### 4.1 What to keep

- explicit session engine + explicit loop state
- message-first runtime
- tool contract with schema, permissions, concurrency flags
- markdown skill system with frontmatter
- file-based long-term memory
- transcript persistence and resume
- multi-path recovery strategy

### 4.2 What to simplify for v1

- no React/Ink UI
- no plugin marketplace
- no remote workers
- no heavy MCP ecosystem in the first milestone
- no deep feature-flag matrix

## 5. Proposed high-level architecture

```text
CLI / API
  -> SessionEngine
    -> PromptBuilder
    -> AgentLoop
      -> ModelAdapter
      -> ToolExecutor
      -> SkillManager
      -> MemoryManager
      -> StabilityManager
    -> TranscriptStore
```

Responsibilities:

- `SessionEngine`: session lifecycle, orchestration, resume, user input normalization
- `PromptBuilder`: stable system prompt assembly
- `AgentLoop`: turn state machine
- `ModelAdapter`: unified streaming/non-streaming LLM interface
- `ToolExecutor`: validation, permission, execution, result normalization
- `SkillManager`: load/resolve/activate skills
- `MemoryManager`: memory storage, recall, consolidation
- `StabilityManager`: compaction, retry, recovery, budgets, guardrails
- `TranscriptStore`: durable logs and restore support

## 6. Proposed project structure

```text
unified_assist/
  README.md
  IMPLEMENTATION_PLAN.md
  pyproject.toml
  src/
    unified_assist/
      __init__.py
      app/
        session_engine.py
        app_config.py
      loop/
        agent_loop.py
        state.py
        transitions.py
      llm/
        base.py
        openai_adapter.py
        anthropic_adapter.py
        stream_parser.py
      messages/
        models.py
        blocks.py
        normalize.py
      prompt/
        builder.py
        sections.py
      tools/
        base.py
        registry.py
        executor.py
        permissions.py
        result_store.py
        builtins/
          bash.py
          read_file.py
          write_file.py
          edit_file.py
          glob_search.py
          think.py
          ask_user.py
      skills/
        models.py
        loader.py
        resolver.py
        hooks.py
      memory/
        manager.py
        store.py
        recall.py
        freshness.py
        consolidator.py
      stability/
        query_guard.py
        transcript_store.py
        resume.py
        compaction.py
        recovery.py
        token_budget.py
      runtime/
        events.py
        attachments.py
        cancellation.py
      utils/
        paths.py
        yaml_frontmatter.py
        logging.py
  skills/
    coding/
      SKILL.md
    planning/
      SKILL.md
  .assist/
    memory/
      MEMORY.md
```

## 7. Core data model

### 7.1 Messages

Use a message-first runtime. Recommended message classes:

- `SystemMessage`
- `UserMessage`
- `AssistantMessage`
- `ToolResultMessage`
- `AttachmentMessage`
- `ProgressEvent`

Assistant content blocks should support:

- `text`
- `thinking` or `reasoning`
- `tool_use`
- `tool_result`

This keeps the Python loop aligned with the Claude Code design and makes replay/resume easier.

### 7.2 Loop state

Recommended state object:

```python
@dataclass
class LoopState:
    messages: list[Message]
    turn_count: int = 1
    max_output_recovery_count: int = 0
    reactive_compaction_attempted: bool = False
    pending_tool_summary: str | None = None
    transition_reason: str = "start"
    context_stats: ContextStats | None = None
```

Add fields later for:

- compaction checkpoints
- token budget
- query chain id
- attachment injection markers
- skill discovery state

## 8. Agent loop design

### 8.1 Turn phases

Each turn should follow this order:

1. prepare `messages_for_query`
2. run context trimming / compaction checks
3. recall relevant memories
4. resolve active skills
5. build prompt sections
6. call model in streaming mode
7. collect assistant blocks and tool requests
8. if no tool request:
   finish or enter recovery path
9. if tool request:
   validate and execute tools
10. convert outputs into `tool_result` messages
11. inject attachments
12. append everything to state and continue

### 8.2 Pseudocode

```python
while True:
    prepared = prepare_context(state)
    prompt = prompt_builder.build(prepared)
    stream = model.generate(prompt, tools=tool_registry.visible_tools())

    assistant_messages, tool_calls = collect_stream(stream)

    if not tool_calls:
        recovery = stability.try_recover(state, assistant_messages)
        if recovery.should_retry:
            state = recovery.next_state
            continue
        return complete(state, assistant_messages)

    tool_results, updated_context = tool_executor.run(tool_calls, state)
    attachments = attachment_manager.collect(updated_context, state)

    state = state.next_turn(
        assistant_messages=assistant_messages,
        tool_results=tool_results,
        attachments=attachments,
    )
```

### 8.3 Why explicit state matters

This gives us:

- resumability
- deterministic transitions
- better debugging
- easier recovery policies
- easier future multi-agent branching

## 9. Tool system design

### 9.1 Tool contract

Use `pydantic` for input schema.

```python
class Tool(Protocol):
    name: str
    input_model: type[BaseModel]

    def is_enabled(self) -> bool: ...
    def is_read_only(self, data: BaseModel) -> bool: ...
    def is_concurrency_safe(self, data: BaseModel) -> bool: ...
    async def validate_input(self, data: BaseModel, ctx: ToolContext) -> ValidationResult: ...
    async def check_permissions(self, data: BaseModel, ctx: ToolContext) -> PermissionResult: ...
    async def call(self, data: BaseModel, ctx: ToolContext) -> ToolResult: ...
```

### 9.2 Runtime flow

Tool execution order should be:

1. lookup tool in registry
2. parse input by schema
3. run semantic validation
4. run permission policy
5. batch by concurrency safety
6. execute
7. normalize output to `ToolResultMessage`

### 9.3 Initial built-in tools

MVP tool set:

- `read_file`
- `write_file`
- `edit_file`
- `glob_search`
- `bash`
- `think`
- `ask_user`

Later:

- `web_search`
- `http_fetch`
- `python_repl`
- `task`
- `subagent`

### 9.4 Permission model

Recommended modes:

- `default`: ask on risky operations
- `accept_edits`: file edits auto-allowed, commands still checked
- `read_only`: only safe tools
- `plan`: no side-effecting tools

This should be runtime-driven, not prompt-only.

### 9.5 AgentTool and subagent layering

For Unified Claw, `subagent` should be exposed to the model through an `AgentTool`, but should not be implemented internally as an ordinary tool handler.

The recommended layering is:

- `AgentTool`: the delegation entrypoint visible to the main agent
- `AgentDefinition`: the role/config definition for a child agent
- `AgentRuntime`: the actual child runtime that executes its own loop

This matches the Claude Code pattern:

- the parent agent uses a tool-shaped interface to delegate work
- the selected child agent still runs a full agent loop with its own context
- subagents are therefore "tool-invoked" at the boundary, but "agent-runtime-driven" internally

Recommended Python shape:

```python
class AgentTool(Tool):
    name = "spawn_agent"

    async def call(self, data: SpawnAgentInput, ctx: ToolContext) -> ToolResult:
        agent_def = agent_registry.resolve(data.agent_type)
        result = await run_agent(
            agent_definition=agent_def,
            parent_context=ctx,
            task_prompt=data.prompt,
        )
        return result.as_tool_result()
```

Important design rules:

- do not flatten a subagent into a one-shot function call
- subagent should have its own messages, loop state, prompt assembly, and cancellation scope
- the parent should receive the child outcome as a tool result
- agent definitions should be configurable independently from tool registration
- later, async/background agents and forked agents can reuse the same runtime

For v1 of Unified Claw:

- keep `AgentTool` in the architecture
- do not implement full multi-agent execution in the first milestone
- define the interface now so later expansion does not require redesign

Suggested Python modules for this layer:

- `tools/builtins/agent.py`
- `agents/definitions.py`
- `agents/runtime.py`
- `agents/registry.py`
- `agents/forking.py`

## 10. Skill system design

### 10.1 Skill format

Use directory format:

```text
skills/
  skill-name/
    SKILL.md
```

Suggested frontmatter:

```yaml
---
name: planning
description: Break complex work into execution steps
when_to_use: When the task is ambiguous or large
allowed_tools: [read_file, glob_search, think]
context: inline
priority: 50
paths:
  - "src/**"
---
```

### 10.2 Skill manager responsibilities

- load global and project skills
- parse frontmatter
- deduplicate by path
- activate path-conditioned skills
- expose active skill prompts to prompt builder
- optionally register lifecycle hooks

### 10.3 Skill philosophy

Skills should not replace the system prompt.

They should act as:

- domain-specific operating guides
- reusable workflows
- tool usage hints
- project-local conventions

## 11. Memory system design

### 11.1 Storage format

Use file-based memory under:

```text
.assist/memory/
  MEMORY.md
  user/
  feedback/
  project/
  reference/
```

Memory categories should mirror Claude Code's typed taxonomy:

- `user`: who the user is, long-lived preferences
- `feedback`: how the assistant should work with the user
- `project`: active project context not derivable from code
- `reference`: external systems, links, playbooks, dashboards

### 11.2 Recall strategy

Do not blindly inject all memories.

Use a two-stage recall pipeline:

1. scan memory headers and descriptions
2. select top relevant entries by heuristic or a small model

For v1:

- default to heuristic scoring by keyword overlap + recency
- optionally add small-model reranking later

### 11.3 Freshness strategy

Every injected memory should carry freshness info:

- `today`
- `yesterday`
- `N days old`

For old memory, add a reminder:

- verify against current code or current project state before asserting as fact

### 11.4 Consolidation strategy

Later, add a background memory consolidation worker:

- scan sessions since last consolidation
- summarize repeated facts
- merge or prune stale memory entries
- update `MEMORY.md` index

This is a phase-2 feature, not MVP blocking work.

## 12. Stability design

### 12.1 Query guard

Add a synchronous guard that prevents overlapping loop execution in one session.

Python version:

- `idle`
- `dispatching`
- `running`

Same reason as Claude Code:

- queue safety
- cancel safety
- no double submit races

### 12.2 Transcript-first persistence

Before entering the model loop:

- persist accepted user input to JSONL transcript

During execution:

- append assistant/tool/progress events continuously

Benefits:

- resume after crash
- post-mortem debugging
- auditability

### 12.3 Resume repair

When restoring from transcript:

- filter unresolved tool calls
- drop malformed assistant-only fragments
- append synthetic continuation message when needed

### 12.4 Multi-stage context control

Do not rely on one summarization path.

Recommended layers:

- soft trim: drop low-value transient events
- tool result budget: replace oversized results with persisted previews
- summarization compaction: summarize old turns
- collapse snapshot: keep compacted view rebuildable

### 12.5 Recovery policies

Initial recovery policies:

- prompt too long -> compact and retry once
- max output hit -> inject continuation meta-message
- tool failure -> return standardized error result, do not crash loop
- user interrupt -> synthesize missing tool results and stop cleanly
- model fallback -> retry with backup model when configured

### 12.6 Cancellation model

Use parent/child cancel scopes:

- session cancel scope
- per-turn cancel scope
- per-tool cancel scope

This lets one failed tool cancel siblings without destroying the whole session when unnecessary.

## 13. Prompt design

System prompt should be section-based, not one large string.

Recommended sections:

- core role
- operating rules
- environment info
- active skills
- memory instructions
- recalled memories
- output style
- current session guidance

Benefits:

- easier caching
- easier testing
- easier feature toggling
- easier project-specific overrides

## 14. Suggested implementation stack

- `pydantic`: schemas for tools, messages, config
- `anyio` or `asyncio`: async runtime
- `httpx`: model API client
- `typer`: CLI
- `rich`: console rendering
- `orjson`: transcript serialization
- `python-frontmatter` or custom parser: skill/memory markdown frontmatter
- `sqlite3` optional: metadata index for sessions and memory headers

## 15. MVP scope

### 15.1 Must have

- session engine
- explicit agent loop
- streaming model adapter
- core file/code tools
- project skills loader
- file-based memory
- transcript persistence and resume
- basic prompt-too-long and max-output recovery

### 15.2 Can wait

- multi-agent orchestration
- background consolidation
- GUI/TUI
- plugin marketplace
- remote execution
- full MCP compatibility

## 16. Delivery roadmap

### Phase 1: scaffold

- create package structure
- define message and tool schemas
- implement transcript store
- implement basic CLI entry

### Phase 2: runnable assistant

- implement model adapter
- implement agent loop
- implement file/bash/search tools
- produce first usable coding assistant

### Phase 3: modular intelligence

- implement skills loader
- implement memory store + selective recall
- implement prompt section builder

### Phase 4: hardening

- add compaction
- add recovery policies
- add resume repair
- add observability and event logs

### Phase 5: advanced agent features

- subagents
- task system
- background consolidation
- richer permission policies

## 17. Recommended next coding step

The next implementation step should be:

1. scaffold `pyproject.toml` and `src/unified_assist/`
2. implement message models + transcript store
3. implement `Tool` base protocol + `ToolRegistry`
4. implement `SessionEngine` and minimal `AgentLoop`
5. wire in `read_file`, `glob_search`, `bash`, `write_file`, `edit_file`

This ordering gives us a usable vertical slice early, while staying faithful to the Claude Code architecture.
