from __future__ import annotations

from unified_assist.skills.models import Skill


def _bundled_skill(
    *,
    name: str,
    description: str,
    when_to_use: str,
    allowed_tools: list[str],
    body: str,
    context: str = "inline",
    argument_hint: str = "",
    disable_model_invocation: bool = False,
) -> Skill:
    return Skill(
        name=name,
        description=description,
        body=body.strip(),
        when_to_use=when_to_use,
        allowed_tools=allowed_tools,
        context=context,
        auto_activate=False,
        metadata={
            "source": "bundled",
            "user_invocable": True,
            "argument_hint": argument_hint,
            "disable_model_invocation": disable_model_invocation,
        },
    )


def load_bundled_skills() -> list[Skill]:
    return [
        _bundled_skill(
            name="update-config",
            description="Update Claude-style project or local settings safely and explain the effect of each change.",
            when_to_use="Use when the user wants to change Claude or project assistant behavior, permissions, hooks, or model defaults.",
            allowed_tools=["Read", "Write", "Edit", "Glob"],
            body="""
# Update Config

## Goal
Make a precise configuration change without clobbering existing settings.

## Steps
1. Identify the right target file and scope. Prefer repository-local config before global config unless the user explicitly asks for a global change.
2. Read the existing file before editing it. Preserve unrelated keys and keep the file valid JSON.
3. Apply the smallest possible diff. If a setting can be expressed more narrowly, prefer the narrower rule.
4. Explain what changed, what the new setting does, and any precedence or override behavior the user should know.

## Rules
- Do not replace the whole file when a small edit is enough.
- If the requested setting is ambiguous, ask a focused follow-up question.
- If a setting affects permissions or hooks, call out the safety implications explicitly.
""",
            argument_hint="[setting change]",
        ),
        _bundled_skill(
            name="keybindings",
            description="Edit assistant keybinding configuration carefully, preserving existing bindings and conflicts.",
            when_to_use="Use when the user wants to add, remove, or rebind assistant shortcuts.",
            allowed_tools=["Read", "Write", "Edit"],
            body="""
# Keybindings

## Goal
Modify keybinding configuration without losing existing user customizations.

## Steps
1. Read the current keybindings file if it exists.
2. Merge the requested change into the existing structure instead of replacing the full document.
3. If a rebind is requested, remove the old shortcut and add the new one in the same pass.
4. Explain any likely conflicts, especially terminal or OS-reserved shortcuts.

## Rules
- Prefer minimal edits.
- Preserve schema and comments when possible.
- If a binding looks platform-specific, mention that in the final explanation.
""",
            argument_hint="[shortcut change]",
        ),
        _bundled_skill(
            name="verify",
            description="Verify a change by running the relevant code paths, tests, and realistic checks instead of only reading code.",
            when_to_use="Use when the user asks to verify behavior, confirm a fix, reproduce a bug, or gather evidence that a change really works.",
            allowed_tools=["Read", "Glob", "Grep", "Bash", "AskUserQuestion"],
            body="""
# Verify

## Goal
Confirm the code really does what it should with concrete evidence.

## Steps
1. Read the changed files or the files most relevant to the user's request.
2. Find the available verification paths: unit tests, integration tests, dev server flows, scripts, or reproducible shell commands.
3. Prefer actually running the most relevant checks. If there are multiple useful checks, run the focused one first, then broader coverage if needed.
4. Capture evidence: command output, screenshots, logs, or observed behavior.
5. Report what passed, what failed, and any remaining gaps.

## Rules
- Do not claim something is verified unless you actually observed supporting evidence.
- If you cannot run an important check, say exactly why.
- Distinguish between "tested", "inspected", and "inferred".
""",
            argument_hint="[what to verify]",
        ),
        _bundled_skill(
            name="debug",
            description="Investigate failures using logs, transcripts, configs, and concrete evidence.",
            when_to_use="Use when the user reports an error, failing workflow, broken command, or unexpected runtime behavior.",
            allowed_tools=["Read", "Grep", "Glob", "Bash"],
            body="""
# Debug

## Goal
Explain the most likely cause of the problem and propose the next best fix.

## Steps
1. Restate the issue in concrete terms: command, file, symptom, and expected behavior.
2. Inspect the nearest evidence first: failing command output, logs, stack traces, transcripts, or config files.
3. Search for related code paths and compare expected behavior to observed behavior.
4. Narrow to a likely root cause, then propose the smallest fix or next diagnostic step.

## Rules
- Ground every conclusion in evidence.
- If the evidence is incomplete, present the best current hypothesis and say what would confirm it.
- Prefer the fastest diagnostic step that meaningfully reduces uncertainty.
""",
            argument_hint="[issue description]",
        ),
        _bundled_skill(
            name="lorem-ipsum",
            description="Generate controlled placeholder text with explicit length and tone guidance.",
            when_to_use="Use when the user needs filler copy, placeholder prose, or token-length test text.",
            allowed_tools=["think"],
            body="""
# Lorem Ipsum

## Goal
Produce placeholder text that matches the requested length, tone, and structure.

## Rules
- Keep the output clearly placeholder in nature unless the user asks for realistic copy.
- If the user requests a target length, state whether you are targeting words, lines, paragraphs, or approximate tokens.
- Prefer simple, clean prose over ornamental filler.
""",
            argument_hint="[length or style]",
        ),
        _bundled_skill(
            name="skillify",
            description="Turn a repeatable workflow into a reusable SKILL.md file after clarifying the important details.",
            when_to_use="Use when the user wants to capture a process from this session into a reusable skill.",
            allowed_tools=["Read", "Write", "Edit", "Glob", "Grep", "AskUserQuestion", "Bash"],
            body="""
# Skillify

## Goal
Capture a repeatable workflow as a reusable skill with clear triggers, inputs, and success criteria.

## Steps
1. Analyze the current session or workflow and extract the repeatable pattern.
2. Ask focused questions about the skill name, trigger conditions, inputs, checkpoints, and outputs.
3. Draft a SKILL.md with frontmatter, goal, inputs, steps, success criteria, and hard rules.
4. Show the draft to the user before saving it.
5. Write the skill file only after the user approves the content.

## Rules
- Keep simple workflows simple.
- Include success criteria for each major step.
- Prefer the minimum necessary tool permissions in frontmatter.
""",
            argument_hint="[workflow description]",
            disable_model_invocation=True,
        ),
        _bundled_skill(
            name="remember",
            description="Review durable memory and propose which facts should be promoted, kept, or cleaned up.",
            when_to_use="Use when the user wants to audit memory entries, promote durable facts, or clean up stale memory.",
            allowed_tools=["Read", "Glob", "Grep"],
            body="""
# Remember

## Goal
Review memory and propose improvements without silently mutating durable knowledge.

## Steps
1. Gather the relevant memory layers and any project guidance files.
2. Classify each durable fact: keep, promote, update, merge, or remove.
3. Highlight duplicates, conflicts, and stale facts.
4. Present a structured recommendation list for user approval.

## Rules
- Do not rewrite memory automatically unless the user explicitly asks.
- Separate durable instructions from temporary working notes.
- When a fact may be stale, recommend re-verifying it before promotion.
""",
            argument_hint="[memory review focus]",
        ),
        _bundled_skill(
            name="simplify",
            description="Review changed code for reuse, quality, and efficiency, then clean up what can be improved.",
            when_to_use="Use when the user asks for a cleanup pass, simplification pass, or a higher-quality version of recent code changes.",
            allowed_tools=["Read", "Grep", "Glob", "Bash", "Agent"],
            body="""
# Simplify

## Goal
Improve changed code by reducing duplication, tightening abstractions, and removing unnecessary complexity.

## Steps
1. Inspect the relevant diff or the most recently changed files.
2. Look for existing helpers or patterns that can replace newly duplicated logic.
3. Review for quality issues: redundant state, copy-paste, leaky abstractions, and unnecessary comments.
4. Review for efficiency issues: repeated work, broad scans, unnecessary I/O, or missed batching.
5. Fix the worthwhile issues directly, then summarize what changed.

## Rules
- Prefer direct improvements over long review prose.
- If a suggested cleanup is not worth the churn, note it briefly and skip it.
- Use child agents for bounded parallel review only when it materially helps.
""",
            argument_hint="[additional focus]",
        ),
        _bundled_skill(
            name="batch",
            description="Plan and execute a large multi-file change by decomposing it into clear, mostly independent work units.",
            when_to_use="Use when the user wants a sweeping refactor, migration, or bulk edit that benefits from decomposition and parallelism.",
            allowed_tools=["Read", "Grep", "Glob", "Bash", "AskUserQuestion", "Agent", "TodoWrite"],
            body="""
# Batch

## Goal
Break a large change into manageable units, then execute and verify them systematically.

## Steps
1. Research the full scope of the requested migration or refactor.
2. Decompose the work into concrete units with clear boundaries and expected artifacts.
3. Define a realistic verification recipe for each unit or for the change as a whole.
4. If child agents can help, delegate bounded units with self-contained prompts.
5. Track progress explicitly and summarize the final state of each unit.

## Rules
- If background or isolated worktrees are unavailable, adapt the plan to the current runtime instead of pretending those features exist.
- Keep each unit independently understandable.
- Ask the user for missing verification guidance when the e2e path is unclear.
""",
            argument_hint="<batch instruction>",
            disable_model_invocation=True,
        ),
        _bundled_skill(
            name="stuck",
            description="Diagnose frozen or slow assistant activity by checking processes, logs, and current session artifacts.",
            when_to_use="Use when the user thinks an assistant session, command, or subprocess is stuck or unusually slow.",
            allowed_tools=["Bash", "Read", "Glob", "Grep"],
            body="""
# Stuck

## Goal
Determine whether the session is actually stuck, what it is waiting on, and the safest next step.

## Steps
1. Inspect relevant processes and subprocesses.
2. Check recent logs, transcripts, or command output for the last visible activity.
3. Identify likely causes such as high CPU loops, blocked I/O, waiting child processes, or oversized context.
4. Summarize the evidence and recommend the next recovery step.

## Rules
- Diagnose only; do not kill processes unless the user explicitly asks.
- Distinguish between a slow task and a frozen one.
- Include the exact command or process evidence you used.
""",
            argument_hint="[symptom or pid]",
        ),
    ]
