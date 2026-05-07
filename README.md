# AIDE

CAID (Centralized Asynchronous Isolated Delegation) multi-agent AI orchestrator. Give AIDE a coding task; it decomposes it into a dependency DAG, fans out to N AI agents each in an isolated git worktree, and integrates every branch back into your main branch automatically.

---

## Table of Contents

- [Prerequisites](#prerequisites)
- [Install](#install)
- [Authentication](#authentication)
- [Quick Start](#quick-start)
- [Usage](#usage)
- [Configuration](#configuration)
- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Development](#development)

---

## Prerequisites

- Python 3.11+
- Git
- At least one agentic CLI or API key:
  - [Claude Code](https://docs.anthropic.com/en/docs/claude-code) (`claude`) — free with Claude subscription
  - [OpenAI Codex CLI](https://github.com/openai/codex) (`codex`) — requires OpenAI account
  - [Gemini CLI](https://github.com/google-gemini/gemini-cli) (`gemini`) — free with Google account
  - Or an API key for Anthropic, OpenAI, Google, or Perplexity

---

## Install

### From source

```bash
git clone https://github.com/platfrmrcarl/AIDE.git
cd AIDE
pip install -e .
```

### With optional provider support

```bash
# Anthropic is included by default. For other providers:
pip install -e '.[openai]'      # OpenAI / ChatGPT
pip install -e '.[google]'      # Google Gemini
pip install -e '.[all]'         # All providers
pip install -e '.[dev]'         # Development dependencies (pytest, etc.)
```

---

## Authentication

AIDE uses one provider for **planning** (decomposing tasks into a DAG) and any available agentic CLI for **execution** (running each subtask).

### Planning providers

| Provider | `provider` value | Install extra | API key env var | Subscription CLI |
|----------|-----------------|---------------|-----------------|-----------------|
| Anthropic (Claude) | `anthropic` | *(included)* | `ANTHROPIC_API_KEY` | `claude` ✓ |
| OpenAI (ChatGPT) | `openai` | `aide[openai]` | `OPENAI_API_KEY` | ✗ |
| Google (Gemini) | `google` | `aide[google]` | `GEMINI_API_KEY` | `gemini` ✓ |
| Perplexity | `perplexity` | *(included)* | `PERPLEXITY_API_KEY` | ✗ |

### Auth modes

| Mode | Behavior |
|------|----------|
| `auto` *(default)* | Use API key if env var is set; fall back to subscription CLI otherwise |
| `api_key` | Always use the SDK — error if key not set |
| `subscription` | Always use the provider's CLI — Anthropic and Google only |

### Option 1 — API key

Set the env var for your chosen provider:

```bash
# Anthropic
export ANTHROPIC_API_KEY=sk-ant-...

# OpenAI
export OPENAI_API_KEY=sk-...

# Google
export GEMINI_API_KEY=...

# Perplexity
export PERPLEXITY_API_KEY=pplx-...
```

### Option 2 — Subscription CLI (no API key needed)

Install and authenticate the CLI for your provider, then AIDE will use it automatically:

```bash
# Claude (Anthropic) — requires Claude subscription
npm install -g @anthropic-ai/claude-code
claude login

# Gemini CLI (Google) — free with Google account
npm install -g @google/gemini-cli
gemini auth
```

Set `auth_mode: "subscription"` in `.aide/config.json` to force CLI mode.

### Worker CLI (code execution)

Worker agents auto-detect the best available agentic CLI: `claude` → `codex` → `gemini` (first one found wins). Override with `"worker_cmd": "claude"` in `.aide/config.json`.

---

## Quick Start

### 1. Initialize AIDE in your repo

```bash
cd your-repo
aide init
```

Interactive setup — choose provider, model, and auth mode. For CI/scripted use:

```bash
aide init --no-interactive
```

### 2. Run a task

```bash
aide run "Add input validation to all API endpoints"
```

AIDE will:
1. Call your configured LLM to decompose the task into a DAG of subtasks
2. Spawn N agents in isolated git worktrees (auto-determined by complexity)
3. Merge each passing branch back into your working tree

### 3. Check progress

```bash
aide status
```

### 4. Clean up

```bash
aide clean
```

---

## Usage

### `aide init [REPO_PATH] [OPTIONS]`

Initializes AIDE inside a git repository. Creates `.aide/` with a SQLite message bus, config, and directories for worktrees and run logs.

```bash
aide init                     # interactive, current directory
aide init /path/to/repo       # interactive, specific path
aide init --no-interactive    # skip prompts, write defaults
```

**Interactive prompts:**

```
Provider? [anthropic/openai/google/perplexity] (anthropic):
Model? (claude-opus-4-7):
Auth mode? [auto/api_key/subscription] (auto):
API key env var? (ANTHROPIC_API_KEY):
Detected worker CLI: claude ✓
```

Safe to re-run — exits early if already initialized.

---

### `aide run PROMPT [OPTIONS]`

Decomposes the prompt into subtasks, fans out to agents, and integrates results.

```bash
# Simple prompt
aide run "Refactor the auth module to use JWT"

# Explicit agent count
aide run "Add unit tests for all controllers" --agents 8

# Read prompt from a markdown file
aide run --file tasks.md

# Run against a different repo
aide run "Fix all linting errors" --repo /path/to/other-repo

# Custom verify command before merging each branch
aide run "Migrate DB schema" --verify "pytest tests/db/"
```

**Options:**

| Option | Description |
|--------|-------------|
| `PROMPT` | Task description (positional) |
| `--file FILE` | Read prompt from a `.md` file |
| `--repo PATH` | Target repository (default: `.`) |
| `--agents N` | Override auto-computed agent count |
| `--verify CMD` | Run this command before merging each agent branch |

**Agent count auto-scaling** (based on complexity score 1–100):

| Score | Agents |
|-------|--------|
| 1–20 | 3 |
| 21–40 | 5–10 |
| 41–60 | 10–20 |
| 61–80 | 20–50 |
| 81–100 | 50–100 |

---

### `aide status [OPTIONS]`

Shows run history and per-task outcomes.

```bash
aide status                         # last 5 runs
aide status --run-id abc123         # tasks for a specific run
aide status --repo /path/to/repo    # different repo
```

**Options:**

| Option | Description |
|--------|-------------|
| `--repo PATH` | Target repository (default: `.`) |
| `--run-id ID` | Show individual task statuses for a run |

---

### `aide clean [OPTIONS]`

Removes finished agent worktrees.

```bash
aide clean                  # remove all finished worktrees
aide clean --all            # remove all worktrees (including in-progress)
aide clean --repo /path     # different repo
```

---

## Configuration

`.aide/config.json` is written by `aide init` and can be edited at any time:

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
| `provider` | `"anthropic"` | LLM for task planning: `anthropic`, `openai`, `google`, `perplexity` |
| `model` | `"claude-opus-4-7"` | Model name passed to the provider |
| `auth_mode` | `"auto"` | `"auto"` \| `"api_key"` \| `"subscription"` |
| `api_key_env` | `"ANTHROPIC_API_KEY"` | Env var name that holds the API key |
| `worker_cmd` | `"auto"` | Worker CLI: `"auto"` detects `claude`/`codex`/`gemini` on PATH |
| `verify_command` | `null` | Shell command run before merging each branch. Merge skipped if it exits non-zero. |
| `default_agent_count` | `null` | Fixed agent count for all runs (overrides auto-scaling). |
| `worker_timeout_seconds` | `120` | Kill an agent after this many seconds of inactivity. |
| `max_concurrent_workers` | `20` | Max agents running in parallel. |

### Switching providers mid-project

Edit `provider`, `model`, and `api_key_env` directly in `.aide/config.json` — no re-initialization needed.

```json
{
  "provider": "openai",
  "model": "gpt-4o",
  "auth_mode": "api_key",
  "api_key_env": "OPENAI_API_KEY"
}
```

---

## How It Works

```
You: aide run "Add rate limiting to all API endpoints"
       │
       ▼
1. Plan — LLM scores complexity (e.g. 45/100) and generates a DAG:
           t1: Add rate-limit middleware          (no deps)
           t2: Wire middleware into Express app   (depends on t1)
           t3: Write integration tests            (depends on t2)
           t4: Update API docs                    (depends on t1)
       │
       ▼
2. Dispatch — Manager fans out dependency-free tasks to agents in parallel.
              Each agent gets an isolated git worktree on branch aide/<run>/<agent>.
       │
       ▼
3. Execute — Each worker writes TASK.md into its worktree and spawns
             the agentic CLI (claude/codex/gemini) to complete the work.
       │
       ▼
4. Integrate — When an agent finishes, the verify command runs.
               Passing branches are merged back. Dependent tasks unlock.
       │
       ▼
5. Report — aide status shows per-run and per-task outcomes.
```

Key properties:
- **No shared state** — each agent has its own working tree; no file conflicts
- **DAG ordering** — tasks only start when all their dependencies are merged
- **Automatic integration** — branches are merged without manual intervention
- **Provider-agnostic** — swap planning LLM without changing how workers run

---

## Architecture

```
CLI (click)
 │
 ├── Planner → provider adapter → LLM API/CLI → subtask DAG + complexity score
 │              (anthropic | openai | google | perplexity)
 │
 └── Manager (asyncio)
      ├── Taskbox (SQLite) — message bus for task/agent/run state
      ├── Workspace — git worktree lifecycle (create, symlink env files)
      ├── Workers (N subprocesses) — each spawns agentic CLI in isolated worktree
      └── Integration Engine — verify → merge → unlock dependents
```

**Repo layout:**

```
aide/
  providers/
    __init__.py       # SUPPORTED_PROVIDERS, get_provider(), detect_worker_cmd()
    anthropic.py      # api_key: SDK  |  subscription: claude --print
    openai.py         # api_key: SDK only
    google.py         # api_key: SDK  |  subscription: gemini --print
    perplexity.py     # api_key: httpx POST to api.perplexity.ai
  cli.py              # Click commands: init, run, status, clean
  manager.py          # asyncio orchestrator — dispatch, monitor, integrate
  planner.py          # prompt → Plan (DAG of SubTasks + complexity score)
  worker.py           # async subprocess wrapper for agentic CLI
  workspace.py        # git worktree creation, config I/O
  integration.py      # verify command + git merge
  taskbox.py          # SQLite message bus
  models.py           # Plan, SubTask, RunRecord, AgentRecord, Message
```

---

## Development

```bash
# Install with dev dependencies
pip install -e '.[dev]'

# Run all tests
pytest

# Run tests excluding the slow timeout test (~100s)
pytest --ignore=tests/test_worker.py

# Run only the worker timeout test
pytest tests/test_worker.py
```

---

## License

MIT
