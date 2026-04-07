from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from unified_assist.agents.registry import AgentRegistry
from unified_assist.app.app_config import AppConfig
from unified_assist.app.session_engine import SessionEngine
from unified_assist.llm import MiniMaxAdapter, MiniMaxConfig
from unified_assist.loop.agent_loop import AgentLoop
from unified_assist.memory.manager import MemoryManager
from unified_assist.prompt.builder import PromptBuilder
from unified_assist.skills.loader import load_all_skills
from unified_assist.stability.token_budget import TokenBudget
from unified_assist.stability.transcript_store import TranscriptStore
from unified_assist.tools.base import ToolContext
from unified_assist.tools.builtins import builtin_tools
from unified_assist.tools.executor import ToolExecutor
from unified_assist.tools.registry import ToolRegistry
from unified_assist.tools.result_store import ToolResultStore


DEFAULT_MODEL = "MiniMax-M2.7"
DEFAULT_BASE_URL = "https://api.minimaxi.com/v1"


def build_minimax_session_engine(
    *,
    cwd: Path,
    api_key: str,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_BASE_URL,
    session_id: str = "minimax-smoke",
    token_budget: int = 8000,
) -> SessionEngine:
    config = AppConfig.from_root(cwd, session_id=session_id)
    model_adapter = MiniMaxAdapter(
        MiniMaxConfig(
            api_key=api_key,
            model=model,
            base_url=base_url,
        )
    )
    tool_registry = build_builtin_tool_registry()
    tool_executor = ToolExecutor(tool_registry, ToolResultStore(config.tool_results_dir))
    memory_manager = MemoryManager.from_config(config)
    memory_manager.prepare()
    skills = load_all_skills(config.skills_dir)
    loop = AgentLoop(
        model=model_adapter,
        prompt_builder=PromptBuilder(),
        tool_executor=tool_executor,
        tool_context=ToolContext(cwd=cwd),
        memory_manager=memory_manager,
        skills=skills,
        max_turns=8,
        token_budget=TokenBudget(total_tokens=token_budget),
    )
    return SessionEngine(
        config=config,
        agent_loop=loop,
        transcript_store=TranscriptStore(config.transcripts_dir),
        agent_registry=AgentRegistry.with_builtins(),
    )


def build_builtin_tool_registry(*, include_agent_tool: bool = True) -> ToolRegistry:
    registry = ToolRegistry()
    for tool in builtin_tools(include_agent_tool=include_agent_tool):
        registry.register(tool)
    return registry


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Unified Claw with MiniMax.")
    parser.add_argument("prompt", nargs="?", help="One-shot task prompt. Omit to start interactive mode.")
    parser.add_argument("--workdir", default=os.environ.get("MINIMAX_WORKDIR", os.getcwd()))
    parser.add_argument("--model", default=os.environ.get("MINIMAX_MODEL", DEFAULT_MODEL))
    parser.add_argument("--base-url", default=os.environ.get("MINIMAX_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--session-id", default=os.environ.get("MINIMAX_SESSION_ID", "minimax-smoke"))
    parser.add_argument(
        "--show-tool-results",
        action="store_true",
        default=_env_flag("MINIMAX_SHOW_TOOL_RESULTS"),
        help="Print tool_result messages in addition to assistant messages.",
    )
    return parser


async def run_prompt(
    engine: SessionEngine,
    prompt: str,
    *,
    show_tool_results: bool = False,
) -> int:
    previous_len = len(engine.messages)
    state = await engine.submit(prompt)
    new_messages = state.messages[previous_len + 1 :]
    _render_messages(new_messages, show_tool_results=show_tool_results)
    return 1 if _last_assistant_is_error(new_messages) else 0


async def run_interactive_session(
    engine: SessionEngine,
    *,
    show_tool_results: bool = False,
) -> int:
    print(f"Unified Claw interactive session in {engine.config.root_dir}")
    print("Type 'exit' or 'quit' to stop.")
    while True:
        try:
            prompt = input("you> ").strip()
        except EOFError:
            print()
            return 0
        if not prompt:
            continue
        if prompt.lower() in {"exit", "quit"}:
            return 0
        status = await run_prompt(engine, prompt, show_tool_results=show_tool_results)
        if status != 0:
            return status


async def _main(argv: list[str] | None = None) -> int:
    parser = build_argument_parser()
    args = parser.parse_args([] if argv is None else argv)
    api_key = os.environ.get("MINIMAX_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("MINIMAX_API_KEY is required")
    cwd = Path(args.workdir).resolve()
    engine = build_minimax_session_engine(
        cwd=cwd,
        api_key=api_key,
        model=args.model,
        base_url=args.base_url,
        session_id=args.session_id,
    )

    if args.prompt:
        return await run_prompt(
            engine,
            args.prompt,
            show_tool_results=args.show_tool_results,
        )

    return await run_interactive_session(
        engine,
        show_tool_results=args.show_tool_results,
    )


def main() -> None:
    raise SystemExit(asyncio.run(_main(sys.argv[1:])))


def _render_messages(messages: list, *, show_tool_results: bool) -> None:
    for message in messages:
        if message.type == "progress":
            print(f"[progress] {message.content}")
        elif message.type == "assistant" and message.text:
            print(f"assistant> {message.text}")
        elif show_tool_results and message.type == "tool_result":
            for result in message.results:
                print(f"[tool_result] {result.content}")


def _last_assistant_is_error(messages: list) -> bool:
    for message in reversed(messages):
        if getattr(message, "type", "") == "assistant":
            return bool(getattr(message, "is_error", False))
    return False


def _env_flag(name: str) -> bool:
    value = os.environ.get(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    main()
