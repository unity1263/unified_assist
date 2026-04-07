# Unified Claw

Python implementation plan for a super-intelligent assistant inspired by Claude Code.

Current focus: architecture extraction and implementation design.

See [IMPLEMENTATION_PLAN.md](./IMPLEMENTATION_PLAN.md) for:

- the core Claude Code architecture patterns worth preserving
- the Python project structure for `unified_assist`
- the MVP scope and implementation roadmap

See [EXTENDING.md](./EXTENDING.md) for:

- how to add a new tool
- how to add a local or bundled skill
- where to register extensions
- how to test them

## MiniMax Smoke Run

`unified_assist` now includes a MiniMax provider wrapper for `MiniMax-M2.7`.

Use environment variables so the API key does not get committed:

```bash
export MINIMAX_API_KEY=...
export MINIMAX_MODEL=MiniMax-M2.7
export MINIMAX_BASE_URL=https://api.minimaxi.com/v1
python3 -m unified_assist.app.minimax_runner "Inspect this repo and summarize the architecture."
```

Optional:

```bash
export MINIMAX_PROMPT="Reply with one short sentence confirming the connection."
export MINIMAX_WORKDIR=/path/to/workspace
```

If you omit the prompt, the runner starts an interactive session with the default toolset:

```bash
python3 -m unified_assist.app.minimax_runner
```

The full runner automatically wires:

- built-in tools:
  `read_file`, `write_file`, `edit_file`, `glob_search`, `bash`, `think`, `ask_user`, `spawn_agent`
- Claude Code-compatible tools:
  `Read`, `Write`, `Edit`, `Glob`, `Grep`, `Bash`, `AskUserQuestion`, `Skill`, `ToolSearch`, `TodoWrite`, `Agent`, `Task`, `WebFetch`, `WebSearch`, `LSP`
- workspace memory under `.assist/memory`
- bundled skills:
  `update-config`, `keybindings`, `verify`, `debug`, `lorem-ipsum`, `skillify`, `remember`, `simplify`, `batch`, `stuck`
- local skills under `skills/`
- transcript persistence under `.assist/transcripts`
# unified_assist
