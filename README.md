# galaxy

CAID (Centralized Asynchronous Isolated Delegation) multi-agent AI orchestrator. Breaks a coding task into a dependency DAG, spawns Claude Code agents in isolated git worktrees, and integrates the results back to your main branch.

## Install

```bash
pip install -e .
```

Requires Python 3.11+ and the `ANTHROPIC_API_KEY` environment variable.

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

## Quick start

```bash
cd your-repo

# Initialize galaxy (creates .galaxy/ structure)
galaxy init

# Run a task — galaxy auto-determines agent count
galaxy run "Add input validation to all API endpoints"

# Specify agent count explicitly
galaxy run "Refactor auth module" --agents 5

# Run from a markdown task file
galaxy run --file tasks.md

# Check run status
galaxy status

# Clean up finished worktrees
galaxy clean
```

## Commands

### `galaxy init [REPO_PATH]`

Creates the `.galaxy/` workspace structure inside a git repository.

```
.galaxy/
  galaxy.db       # SQLite message bus
  config.json     # Configuration
  worktrees/      # Agent workspaces (created at runtime)
  runs/           # Run logs
```

Defaults to the current directory. Safe to run multiple times.

### `galaxy run PROMPT [OPTIONS]`

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

### `galaxy status [OPTIONS]`

Shows the last 5 runs and their statuses.

| Option | Description |
|--------|-------------|
| `--repo PATH` | Target repository (default: `.`) |
| `--run-id ID` | Show tasks for a specific run |

### `galaxy clean [OPTIONS]`

Removes all finished worktrees.

| Option | Description |
|--------|-------------|
| `--repo PATH` | Target repository (default: `.`) |
| `--all` | Remove all worktrees |

## Configuration

`.galaxy/config.json` is created by `galaxy init` and can be edited:

```json
{
  "verify_command": "pytest",
  "default_agent_count": null,
  "worker_timeout_seconds": 120,
  "anthropic_model": "claude-opus-4-7",
  "max_concurrent_workers": 20
}
```

| Key | Default | Description |
|-----|---------|-------------|
| `verify_command` | `null` | Run before merging each agent branch. Auto-detected if null (`pytest`, `npm test`, `make test`). |
| `default_agent_count` | `null` | Override auto-computed count for all runs. |
| `worker_timeout_seconds` | `120` | Kill agent after this many seconds of inactivity. |
| `anthropic_model` | `claude-opus-4-7` | Model used for task decomposition. |
| `max_concurrent_workers` | `20` | Max agents running simultaneously. |

## How it works

1. **Plan** — The Anthropic API decomposes your prompt into a directed acyclic graph (DAG) of subtasks with dependency ordering.
2. **Dispatch** — The manager fans out each wave of dependency-free tasks to worker agents.
3. **Isolate** — Each agent gets a fresh `git worktree` on a dedicated branch (`galaxy/<run-id>/<agent-id>`), so no two agents touch the same working tree.
4. **Execute** — Workers write a `TASK.md` to their worktree and spawn `claude --print` as a subprocess.
5. **Integrate** — On completion, the verify command runs, and passing branches are merged back. Dependent tasks are unlocked.
6. **Report** — `galaxy status` shows per-run and per-task outcomes.

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
