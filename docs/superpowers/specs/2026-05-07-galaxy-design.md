# AIDE: CAID Multi-Agent Orchestrator — Design Spec

**Date:** 2026-05-07  
**Status:** Approved  
**Repo:** platfrmrcarl/galaxy

---

## Overview

`aide` is a Python CLI tool that implements Centralized Asynchronous Isolated Delegation (CAID) for distributing coding tasks across multiple AI agents (Claude Code). Each agent operates in an isolated git worktree to prevent conflicts. A Manager orchestrator decomposes tasks into a Directed Acyclic Graph (DAG), fans out to N workers, monitors progress via SQLite, and integrates completed work back to the main branch.

---

## Goals

1. Accept a task as a natural language prompt or a `.md` file of tasks
2. Auto-determine optimal agent count based on task complexity (override with `--agents N`)
3. Provision isolated git worktrees for each agent
4. Delegate subtasks asynchronously to Claude Code CLI workers
5. Integrate completed work with test-gating and merge management
6. Expose a clean CLI: `aide init`, `aide run`, `aide status`, `aide clean`

---

## Non-Goals

- Multi-provider support (Gemini, GPT) — future work
- Remote execution or cloud infrastructure — local only
- GUI — CLI only

---

## Architecture

### Component Overview

```
User
 │
 ▼
CLI (click)  ──────────────────────────────────────────────
 │                                                         │
 ▼                                                         ▼
Planner (Anthropic API)                              Manager (asyncio)
 │                                                         │
 │  returns: subtask DAG + agent count                     │  dispatches/monitors
 ▼                                                         ▼
Plan stored in runs/<id>/plan.json           Workers (N subprocesses)
                                              each in isolated git worktree
                                                          │
                                                    Taskbox (SQLite)
                                                          │
                                                   Integration Engine
                                                   (test → merge → notify)
                                                          │
                                                    main branch ✓
```

### Module Responsibilities

| Module | Responsibility |
|---|---|
| `cli.py` | Click entry points: init, run, status, clean |
| `models.py` | Dataclasses: Task, Agent, Message, Plan, RunState |
| `taskbox.py` | SQLite message bus — CRUD for tasks/messages/agents |
| `workspace.py` | Git worktree lifecycle, branch naming, .env/.cache symlinking |
| `planner.py` | Calls Anthropic API to decompose task → DAG + agent count |
| `worker.py` | Wraps `claude --print` subprocess; writes stdout to Taskbox |
| `manager.py` | asyncio event loop — fan-out, monitor, trigger integration |
| `integration.py` | Run verify command → merge branch → notify dependent workers |

(Module paths are under `aide/` after the package rename.)

---

## Data Models

```python
@dataclass
class SubTask:
    id: str
    description: str
    depends_on: list[str]   # IDs of tasks that must complete first
    assigned_agent: str | None
    status: Literal["pending", "in_progress", "complete", "failed"]
    worktree_path: str | None
    branch: str | None

@dataclass
class Plan:
    run_id: str
    original_prompt: str
    agent_count: int
    tasks: list[SubTask]
    complexity_score: int    # 1–100

@dataclass
class Message:
    id: str
    type: Literal["DISPATCH", "PROGRESS", "COMPLETE", "ERROR", "ESCALATE", "SYNC"]
    from_agent: str
    to_agent: str
    payload: dict
    created_at: datetime

@dataclass
class AgentRecord:
    id: str
    run_id: str
    worktree_path: str
    branch: str
    task_id: str
    pid: int | None
    status: Literal["idle", "working", "done", "failed"]
    last_heartbeat: datetime
```

---

## Taskbox (SQLite Schema)

```sql
CREATE TABLE tasks (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    description TEXT NOT NULL,
    depends_on TEXT,        -- JSON array of task IDs
    assigned_agent TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    worktree_path TEXT,
    branch TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    from_agent TEXT NOT NULL,
    to_agent TEXT NOT NULL,
    payload TEXT NOT NULL,  -- JSON
    created_at TEXT NOT NULL,
    processed INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE agents (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    worktree_path TEXT NOT NULL,
    branch TEXT NOT NULL,
    task_id TEXT NOT NULL,
    pid INTEGER,
    status TEXT NOT NULL DEFAULT 'idle',
    last_heartbeat TEXT NOT NULL
);

CREATE TABLE runs (
    id TEXT PRIMARY KEY,
    prompt TEXT NOT NULL,
    agent_count INTEGER NOT NULL,
    complexity_score INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    started_at TEXT NOT NULL,
    completed_at TEXT
);
```

---

## Planner

The Planner calls the Anthropic API with the user's task and returns:
- `complexity_score` (1–100)
- `agent_count` (computed or user-supplied)
- `tasks`: list of subtasks with dependency graph

### Agent Count Formula

| Complexity Score | Agent Count |
|---|---|
| 1–20 | 3 |
| 21–40 | 5–10 |
| 41–60 | 10–20 |
| 61–80 | 20–50 |
| 81–100 | 50–100 |

When `--agents N` is supplied, skip the auto-count and use N directly.

### Planner Prompt Pattern

The Planner sends a structured system prompt instructing Claude to output JSON:
```json
{
  "complexity_score": 45,
  "agent_count": 12,
  "tasks": [
    {
      "id": "t1",
      "description": "...",
      "depends_on": []
    },
    {
      "id": "t2",
      "description": "...",
      "depends_on": ["t1"]
    }
  ]
}
```

---

## Workspace Manager

### Worktree Layout
```
<repo>/.aide/
  worktrees/
    agent-001/    # git worktree on branch aide/<run-id>/agent-001
    agent-002/
    ...
  aide.db         # SQLite Taskbox
  runs/
    <run-id>/
      plan.json
      shift.log
```

### Operations
- `init_aide(repo_path)` — creates `.aide/` structure, initializes `aide.db`
- `create_worktree(repo_path, run_id, agent_id)` → `(worktree_path, branch_name)`
- `delete_worktree(repo_path, worktree_path)`
- `list_worktrees(repo_path)` → list of active worktrees
- `symlink_env_files(worktree_path, repo_path)` — symlinks `.env`, `node_modules`, `venv`, etc.
- `is_initialized(repo_path)` → bool

---

## Worker

Each Worker:
1. Receives a `SubTask` and a worktree path
2. Writes a `TASK.md` to the worktree root with task context
3. Spawns `claude --print "$(cat TASK.md)"` as an async subprocess
4. Streams stdout to Taskbox as PROGRESS messages
5. On exit-0, sends COMPLETE; on exit-nonzero, sends ERROR

Worker heartbeat writes to `agents` table every 30s.

---

## Manager

The Manager runs an asyncio event loop that:
1. Loads the Plan from Taskbox
2. Finds all tasks with `depends_on == []` (wave 0) and dispatches them
3. Polls Taskbox for COMPLETE/ERROR messages
4. On COMPLETE: triggers Integration Engine for that task; when merged, unlocks dependent tasks (wave N+1)
5. On ERROR: marks task failed, decides retry or ESCALATE
6. On all tasks complete: writes shift.log summary and exits

The Manager uses `asyncio.gather` to run all active workers concurrently.

---

## Integration Engine

For each completed worktree:
1. Run the repo's verify command (auto-detected: `pytest`, `npm test`, `make test`, or configurable)
2. If tests pass: `git merge <branch>` into a `aide/<run-id>/staging` branch
3. Send SYNC message to all active workers so they can `git rebase staging`
4. If tests fail: send ERROR back to Manager; Manager spawns a fix agent

---

## CLI Commands

```bash
# Initialize AIDE for a repo
aide init [REPO_PATH]          # default: current directory

# Run from prompt
aide run "PROMPT" [--repo PATH] [--agents N] [--verify CMD]

# Run from .md file
aide run --file tasks.md [--repo PATH] [--agents N]

# Monitor current/last run
aide status [--run-id ID]

# Clean finished worktrees
aide clean [--repo PATH] [--all]
```

---

## TDD Approach

Tests are written before implementation. Each module has a corresponding test file:

| Test File | What it tests |
|---|---|
| `test_models.py` | Dataclass construction, serialization |
| `test_taskbox.py` | SQLite CRUD, message queuing, status transitions |
| `test_workspace.py` | Worktree create/delete, symlink, init (uses tmp git repo) |
| `test_planner.py` | JSON parsing, agent count formula, mock Anthropic API |
| `test_worker.py` | Subprocess spawning, heartbeat, COMPLETE/ERROR signals (mock claude) |
| `test_manager.py` | Fan-out dispatch, dependency resolution, wave management (mock workers) |
| `test_integration.py` | Verify command detection, merge logic (tmp git repo) |
| `test_cli.py` | CLI commands via Click test runner |

All external dependencies (Anthropic API, `claude` subprocess, git) are mocked in unit tests. Integration tests use real tmp git repos and a mock `claude` script.

---

## Tech Stack

| Dependency | Purpose |
|---|---|
| Python 3.11+ | Language |
| `anthropic` | Claude API for planning |
| `click` | CLI framework |
| `asyncio` (stdlib) | Concurrent worker management |
| `sqlite3` (stdlib) | Taskbox |
| `subprocess` / `asyncio.subprocess` | Worker process management |
| `pytest` | Test runner |
| `pytest-asyncio` | Async test support |
| `pytest-mock` | Mocking |

---

## Installation (Packaging)

```toml
[project]
name = "aide"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["anthropic>=0.40.0", "click>=8.0"]

[project.scripts]
aide = "aide.cli:main"
```

Install: `pip install -e .` (dev) or `pip install aide` (release)

---

## Error Handling

- Worker timeout: if no heartbeat for 120s, Manager kills worker and marks task failed
- Merge conflict: Integration Engine spawns a dedicated conflict-resolution agent in a new worktree
- API rate limit: Planner retries with exponential backoff (max 5 attempts)
- git errors: propagated as ERROR messages with full stderr

---

## Configuration

`<repo>/.aide/config.json` (created by `aide init`):
```json
{
  "verify_command": "pytest",
  "default_agent_count": null,
  "worker_timeout_seconds": 120,
  "anthropic_model": "claude-opus-4-7",
  "max_concurrent_workers": 20
}
```

`ANTHROPIC_API_KEY` must be set in environment.

---

## Success Criteria

- `aide init` creates `.aide/` structure without error
- `aide run "small task"` spawns 3 agents, merges all branches, exits 0
- `aide run "large task" --agents 50` spawns 50 agents across 50 worktrees
- All unit tests pass with `pytest`
- No git conflicts between concurrent workers
- `aide clean` removes all finished worktrees and their branches
