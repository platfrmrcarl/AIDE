# AIDE

CAID (Centralized Asynchronous Isolated Delegation) multi-agent AI orchestrator. Breaks a coding task into a dependency DAG, spawns Claude Code agents in isolated git worktrees, and integrates the results back to your main branch.

## Install

```bash
pip install -e .
```

Requires Python 3.11+.

## Authentication

AIDE supports multiple LLM providers for task planning, each with two auth modes.

### Providers

| Provider | `provider` value | API key env var | Subscription (CLI) |
|----------|-----------------|-----------------|-------------------|
| Anthropic (Claude) | `anthropic` | `ANTHROPIC_API_KEY` | ✓ `claude` CLI |
| OpenAI (ChatGPT) | `openai` | `OPENAI_API_KEY` | ✗ |
| Google (Gemini) | `google` | `GEMINI_API_KEY` | ✓ `gemini` CLI |
| Perplexity | `perplexity` | `PERPLEXITY_API_KEY` | ✗ |

### Auth modes

- **`auto` (default)** — uses API key if env var is set, otherwise falls back to subscription CLI
- **`api_key`** — always use SDK with API key (error if not set)
- **`subscription`** — always use the provider's CLI (Anthropic and Google only)

Configure in `.aide/config.json` or set during `aide init`.

### Optional provider installs

```bash
pip install 'aide[openai]'   # OpenAI support
pip install 'aide[google]'   # Google Gemini support
pip install 'aide[all]'      # All providers
```

### Worker CLI (code execution)

Workers auto-detect the best available agentic CLI: `claude` → `codex` → `gemini`.
Override with `"worker_cmd": "claude"` in `.aide/config.json`.

## Quick start

```bash
cd your-repo

# Initialize AIDE (creates .aide/ structure)
aide init

# Run a task — AIDE auto-determines agent count
aide run "Add input validation to all API endpoints"

# Specify agent count explicitly
aide run "Refactor auth module" --agents 5

# Run from a markdown task file
aide run --file tasks.md

# Check run status
aide status

# Clean up finished worktrees
aide clean
```

## Commands

### `aide init [REPO_PATH]`

Creates the `.aide/` workspace structure inside a git repository.

```
.aide/
  aide.db       # SQLite message bus
  config.json     # Configuration
  worktrees/      # Agent workspaces (created at runtime)
  runs/           # Run logs
```

Defaults to the current directory. Safe to run multiple times.

### `aide run PROMPT [OPTIONS]`

Decomposes the prompt into a subtask DAG using Claude, then fans out to N agents each in an isolated git worktree.

| Option | Description |
|--------|-------------|
| `--file FILE` | Read prompt from a `.md` file instead |
| `--repo PATH` | Target repository (default: `.`) |
| `--agents N` | Override auto-computed agent count |
| `--verify CMD` | Command to run before merging each branch |

Agent count is auto-determined from task complexity (1–100 score):

| Score | Agents |
|-------|--------|
| 1–20 | 3 |
| 21–40 | 5–10 |
| 41–60 | 10–20 |
| 61–80 | 20–50 |
| 81–100 | 50–100 |

### `aide status [OPTIONS]`

Shows the last 5 runs and their statuses.

| Option | Description |
|--------|-------------|
| `--repo PATH` | Target repository (default: `.`) |
| `--run-id ID` | Show tasks for a specific run |

### `aide clean [OPTIONS]`

Removes all finished worktrees.

| Option | Description |
|--------|-------------|
| `--repo PATH` | Target repository (default: `.`) |
| `--all` | Remove all worktrees |

## Configuration

`.aide/config.json` is created by `aide init` and can be edited:

```json
{
  "provider": "anthropic",
  "model": "claude-opus-4-7",
  "auth_mode": "auto",
  "api_key_env": "ANTHROPIC_API_KEY",
  "worker_cmd": "auto",
  "verify_command": null,
  "default_agent_count": null,
  "worker_timeout_seconds": 120,
  "max_concurrent_workers": 20
}
```

| Key | Default | Description |
|-----|---------|-------------|
| `provider` | `"anthropic"` | LLM provider for planning: `anthropic`, `openai`, `google`, `perplexity` |
| `model` | `"claude-opus-4-7"` | Model name for the chosen provider |
| `auth_mode` | `"auto"` | `"auto"` \| `"api_key"` \| `"subscription"` |
| `api_key_env` | `"ANTHROPIC_API_KEY"` | Env var name holding the API key |
| `worker_cmd` | `"auto"` | CLI for agent execution: `"auto"` auto-detects `claude`/`codex`/`gemini` |
| `verify_command` | `null` | Run before merging each branch. Auto-detected if null (`pytest`, `npm test`, `make test`). |
| `default_agent_count` | `null` | Override auto-computed count for all runs. |
| `worker_timeout_seconds` | `120` | Kill agent after this many seconds of inactivity. |
| `max_concurrent_workers` | `20` | Max agents running simultaneously. |

## How it works

1. **Plan** — The Anthropic API decomposes your prompt into a directed acyclic graph (DAG) of subtasks with dependency ordering.
2. **Dispatch** — The manager fans out each wave of dependency-free tasks to worker agents.
3. **Isolate** — Each agent gets a fresh `git worktree` on a dedicated branch (`aide/<run-id>/<agent-id>`), so no two agents touch the same working tree.
4. **Execute** — Workers write a `TASK.md` to their worktree and spawn `claude --print` as a subprocess.
5. **Integrate** — On completion, the verify command runs, and passing branches are merged back. Dependent tasks are unlocked.
6. **Report** — `aide status` shows per-run and per-task outcomes.

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run tests excluding the slow timeout test
pytest --ignore=tests/test_worker.py
pytest tests/test_worker.py  # includes a ~100s timeout test
```

## Architecture

```
CLI (click)
 │
 ├── Planner (Anthropic API) → subtask DAG + complexity score
 │
 └── Manager (asyncio)
      ├── Taskbox (SQLite) — message bus for task/agent/run state
      ├── Workspace — git worktree lifecycle
      ├── Workers (N subprocesses) — each runs `claude --print` in isolated worktree
      └── Integration Engine — verify → merge → unlock dependents
```

## License

MIT
