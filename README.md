<p align="center">
  <img src="logo.png" alt="AIDE" width="320" />
</p>

<h1 align="center">AIDE</h1>
<p align="center"><em>Centralized Asynchronous Isolated Delegation — multi-agent AI orchestrator</em></p>

---

Give AIDE a task. It decomposes it into a dependency DAG, fans out to N AI agents working in parallel, and integrates their results automatically. Works in git repos, plain directories, or embedded inside your own application.

---

## Table of Contents

- [What AIDE Does](#what-aide-does)
- [Prerequisites](#prerequisites)
- [Install](#install)
- [Setting Up Your LLM](#setting-up-your-llm)
- [Workspace Modes](#workspace-modes)
  - [Git Mode — coding in a repository](#git-mode--coding-in-a-repository)
  - [Bare Mode — any task, no git required](#bare-mode--any-task-no-git-required)
- [Quick Start](#quick-start)
- [CLI Reference](#cli-reference)
- [Configuration](#configuration)
- [Using AIDE as a Library](#using-aide-as-a-library)
- [Variant Workers + LLM Judge](#variant-workers--llm-judge)
- [Recipes](#recipes)
- [How It Works](#how-it-works)
- [Architecture](#architecture)
- [Development](#development)

---

## What AIDE Does

AIDE splits a large task into parallel subtasks and runs each one on a real AI agent — Claude, GPT-4o, or Gemini — in an isolated workspace. Results are verified and merged (git mode) or collected into output directories (bare mode).

**Use it for:**
- Refactoring a codebase across many files simultaneously
- Generating content, copy, or analysis from multiple angles at once
- Research tasks that can be parallelized across agents
- Any work that benefits from N agents working concurrently without stepping on each other

---

## Prerequisites

- Python 3.11+
- At least one of:
  - A Claude, OpenAI, Google, or Perplexity **API key**
  - A **subscription CLI** — `claude` (Claude subscription) or `gemini` (free Google account)

Git is only required for git mode. Bare mode works anywhere.

---

## Install

```bash
git clone https://github.com/platfrmrcarl/AIDE.git
cd AIDE
pip install -e .
```

**With extra provider support:**

```bash
pip install -e '.[openai]'   # OpenAI / ChatGPT
pip install -e '.[google]'   # Google Gemini
pip install -e '.[all]'      # All providers
pip install -e '.[dev]'      # Dev dependencies (pytest, etc.)
```

Anthropic is included by default — no extra needed for Claude.

---

## Setting Up Your LLM

AIDE uses one LLM for **planning** (decomposing your task into a DAG) and one or more **worker CLIs** for execution (running each agent subprocess).

### Planning provider

Choose how AIDE calls the planning LLM:

| Provider | Install extra | API key env var | Subscription CLI |
|----------|---------------|-----------------|-----------------|
| Anthropic (Claude) | *(included)* | `ANTHROPIC_API_KEY` | `claude` |
| OpenAI (GPT-4o) | `aide[openai]` | `OPENAI_API_KEY` | — |
| Google (Gemini) | `aide[google]` | `GEMINI_API_KEY` | `gemini` |
| Perplexity | *(included)* | `PERPLEXITY_API_KEY` | — |

#### Option A — API key

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # Claude
export OPENAI_API_KEY=sk-...          # ChatGPT
export GEMINI_API_KEY=...             # Gemini
export PERPLEXITY_API_KEY=pplx-...   # Perplexity
```

#### Option B — Subscription CLI (no API key needed)

```bash
# Claude — requires Claude subscription
npm install -g @anthropic-ai/claude-code
claude login

# Gemini — free with Google account
npm install -g @google/gemini-cli
gemini auth
```

AIDE auto-detects the API key or CLI. Set `auth_mode` explicitly if needed:

```json
{ "auth_mode": "api_key" }        // always use API key
{ "auth_mode": "subscription" }   // always use CLI
{ "auth_mode": "auto" }           // key if set, else CLI (default)
```

### Worker CLI (agent execution)

Workers are the subprocesses that actually complete each subtask. AIDE detects `claude` → `codex` → `gemini` in that order. Pin one with:

```json
{ "worker_cmd": "claude" }
```

Workers need their own auth. If you use `claude` as the worker, `claude login` must have been run. If you use API key mode for planning, the same or a different worker CLI still needs to be available on PATH.

---

## Workspace Modes

AIDE supports two workspace modes controlled by the `mode` config key.

### Git Mode — coding in a repository

In git mode, each agent gets an isolated **git worktree** on its own branch. When the agent commits its work, AIDE runs your verify command and merges the branch back into your working tree.

```
mode: "git"   — force git mode (error if not in a git repo)
mode: "auto"  — use git mode if in a git repo, bare mode otherwise (default)
```

**Setup for a git repo:**

```bash
cd your-project          # must be a git repo
aide init                # interactive setup
aide run "Add caching layer to the database module"
```

`aide init` will ask for provider, model, auth mode, and workspace mode. It writes `.aide/config.json` and creates `.aide/` (add to `.gitignore`).

Each agent works on branch `aide/<run-id>/<agent-id>`. When done, AIDE runs your verify command (`pytest`, `npm test`, etc.) and merges passing branches. Failed agents leave their branches for you to inspect.

**Set a verify command:**

```bash
aide run "Migrate all fetch calls to axios" --verify "npm test"
```

Or persist it in config:

```json
{ "verify_command": "pytest tests/" }
```

**.gitignore recommendation:**

```
.aide/
```

### Bare Mode — any task, no git required

In bare mode, each agent gets a **temp directory** under `.aide/runs/<run-id>/<agent-id>/`. No git ops. Output is preserved until you run `aide clean`.

```
mode: "bare"  — force bare mode
mode: "auto"  — auto-selected when outside a git repo (default)
```

**Run without a git repo:**

```bash
mkdir my-project && cd my-project
aide run "Write five product descriptions for a standing desk"
```

No `aide init` needed — AIDE auto-inits with defaults on first run.

**Specify a custom output directory:**

```bash
aide run "Research competitor pricing strategies" --output ./research-output
```

**Results are printed at the end:**

```
Run abc123: complete (3/3 tasks)
  → .aide/runs/abc123/agent-xyz/
  → .aide/runs/abc123/agent-abc/
  → .aide/runs/abc123/agent-def/
```

Each agent writes its output to its directory. Text output goes to `OUTPUT.md` by convention.

**Clean up:**

```bash
aide clean    # removes all run directories
```

---

## Quick Start

### Git repo — coding task

```bash
cd your-repo
aide init
aide run "Add input validation to all API endpoints"
aide status
```

### No git — content or research task

```bash
mkdir brainstorm && cd brainstorm
aide run "Generate 10 startup name ideas for an AI productivity tool"
# outputs land in .aide/runs/<run-id>/agent-*/OUTPUT.md
```

### Using Claude from the CLI directly (single agent, no parallelism)

AIDE fans out multiple agents by default. For a single-agent run, pass `--agents 1`:

```bash
aide run "Explain this codebase" --agents 1
```

Or use `worker_cmd` to pick which CLI runs:

```bash
# Force Claude Code as the worker
echo '{"worker_cmd": "claude"}' > .aide/config.json
aide run "Refactor this module"

# Force Gemini
echo '{"worker_cmd": "gemini"}' > .aide/config.json
aide run "Write unit tests"

# Force Codex (OpenAI)
echo '{"worker_cmd": "codex"}' > .aide/config.json
aide run "Fix the linting errors"
```

---

## CLI Reference

### `aide init [REPO_PATH] [--no-interactive]`

Creates `.aide/` with config and SQLite database. Works inside or outside a git repo.

```bash
aide init                      # interactive, current directory
aide init /path/to/project     # interactive, specific path
aide init --no-interactive     # defaults only, no prompts
```

Interactive prompts:

```
Provider? [anthropic/openai/google/perplexity] (anthropic):
Model? (claude-opus-4-7):
Auth mode? [auto/api_key/subscription] (auto):
API key env var? (ANTHROPIC_API_KEY):
Workspace mode? [auto/git/bare] (auto):
Detected worker CLI: claude ✓
```

Safe to re-run — exits early if already initialized.

---

### `aide run PROMPT [OPTIONS]`

Decomposes the prompt and runs agents in parallel.

```bash
aide run "Add rate limiting to the API"
aide run "Generate names for a dog grooming startup" --agents 3
aide run --file tasks.md --repo /path/to/project
aide run "Migrate DB schema" --verify "pytest tests/db/"
aide run "Analyze market trends" --output ./analysis
```

| Option | Description |
|--------|-------------|
| `PROMPT` | Task description |
| `--file FILE` | Read prompt from a `.md` file |
| `--repo PATH` | Target directory (default: `.`) |
| `--agents N` | Override auto-computed agent count |
| `--verify CMD` | Run before merging each branch (git mode) |
| `--output DIR` | Output base directory (bare mode) |
| `--variants N` | Run N workers per task; LLM judge picks the best (default: 1) |

**Agent count auto-scaling** (by complexity score 1–100):

| Score | Agents |
|-------|--------|
| 1–20 | 3 |
| 21–40 | 5–10 |
| 41–60 | 10–20 |
| 61–80 | 20–50 |
| 81–100 | 50–100 |

---

### `aide status [OPTIONS]`

```bash
aide status                      # last 5 runs
aide status --run-id abc123      # tasks for a specific run
aide status --repo /path         # different directory
```

---

### `aide clean`

```bash
aide clean                       # remove all finished workspaces
aide clean --repo /path          # different directory
```

Git mode: removes worktrees. Bare mode: deletes run directories.

---

## Configuration

`.aide/config.json` — written by `aide init`, editable at any time:

```json
{
  "mode": "auto",
  "provider": "anthropic",
  "model": "claude-opus-4-7",
  "auth_mode": "auto",
  "api_key_env": "ANTHROPIC_API_KEY",
  "worker_cmd": "auto",
  "verify_command": null,
  "default_agent_count": null,
  "default_variants": 1,
  "worker_timeout_seconds": 120,
  "max_concurrent_workers": 20
}
```

| Key | Default | Description |
|-----|---------|-------------|
| `mode` | `"auto"` | `"auto"` \| `"git"` \| `"bare"` — workspace mode |
| `provider` | `"anthropic"` | Planning LLM and judge LLM: `anthropic`, `openai`, `google`, `perplexity` |
| `model` | `"claude-opus-4-7"` | Model name passed to the planning and judge provider |
| `auth_mode` | `"auto"` | `"auto"` \| `"api_key"` \| `"subscription"` |
| `api_key_env` | `"ANTHROPIC_API_KEY"` | Env var holding the API key |
| `worker_cmd` | `"auto"` | Worker CLI: `"auto"` detects `claude`/`codex`/`gemini` on PATH |
| `verify_command` | `null` | Shell command run before merging each branch (git mode) |
| `default_agent_count` | `null` | Fixed agent count — overrides auto-scaling |
| `default_variants` | `1` | Default workers per task for variant selection (overridden by `--variants`) |
| `worker_timeout_seconds` | `120` | Kill agent after this many seconds |
| `max_concurrent_workers` | `20` | Max agents running in parallel |

**Switch providers without re-initializing:**

```json
{
  "provider": "openai",
  "model": "gpt-4o",
  "auth_mode": "api_key",
  "api_key_env": "OPENAI_API_KEY"
}
```

---

## Using AIDE as a Library

Embed AIDE in your own Python application to dispatch parallel agents programmatically.

```python
import asyncio
from pathlib import Path
from aide.planner import plan_task
from aide.manager import run_manager
from aide.taskbox import Taskbox
from aide.workspace import init_aide

async def run_parallel_agents(task: str, project_dir: Path) -> dict:
    init_aide(project_dir)

    plan = plan_task(
        task,
        provider="anthropic",
        model="claude-opus-4-7",
        auth_mode="auto",
    )

    taskbox = Taskbox(project_dir / ".aide" / "aide.db")

    result = await run_manager(
        plan,
        project_dir,
        taskbox,
        mode="bare",           # no git required
        max_concurrent=5,
        worker_timeout=300,
    )

    return result

# result = {
#   "run_id": "abc123",
#   "status": "complete",
#   "completed": 3,
#   "failed": 0,
#   "total": 3,
#   "output_paths": ["/path/.aide/runs/abc123/agent-xyz", ...]
# }

result = asyncio.run(run_parallel_agents(
    "Analyze user reviews and extract the top 5 pain points",
    Path("./workspace"),
))

for path in result["output_paths"]:
    output = (Path(path) / "OUTPUT.md").read_text()
    print(output)
```

### Programmatic git mode

```python
result = await run_manager(
    plan,
    repo_path=Path("/path/to/your/repo"),
    taskbox=taskbox,
    mode="git",
    verify_cmd="pytest tests/",
    max_concurrent=10,
)
```

### Custom output directory

```python
result = await run_manager(
    plan,
    repo_path=project_dir,
    taskbox=taskbox,
    mode="bare",
    output_dir=Path("/tmp/my-agent-outputs"),
)
```

### Orchestrating agents from a web service

```python
from fastapi import FastAPI
from aide.planner import plan_task
from aide.manager import run_manager
from aide.taskbox import Taskbox
from aide.workspace import init_aide
import asyncio
from pathlib import Path

app = FastAPI()

@app.post("/run-agents")
async def run_agents(task: str):
    workspace = Path(f"/tmp/aide-runs/{task[:20]}")
    workspace.mkdir(parents=True, exist_ok=True)
    init_aide(workspace)

    plan = plan_task(task, provider="anthropic", model="claude-opus-4-7")
    taskbox = Taskbox(workspace / ".aide" / "aide.db")

    result = await run_manager(plan, workspace, taskbox, mode="bare")
    return result
```

---

## Variant Workers + LLM Judge

Run N workers on the same task in parallel, then let an LLM judge select the best result. Useful when output quality matters and you want the strongest answer rather than the first one.

```bash
aide run "Implement the auth middleware" --variants 3
```

### How it works

```
task → spawn N workers in parallel (each in its own isolated workspace)
            ↓
       test gate: run verify command on each output
            ↓
       survivors → LLM judge reads each diff/output, picks the best
            ↓
       winner merges → task complete
```

**Stage 1 — Test gate:** AIDE runs your verify command on every worker's output. Workers that fail are excluded from judging. If none pass, all are sent to the judge anyway (no output is discarded silently).

**Stage 2 — LLM judge:** The judge LLM receives each surviving output (git diff in git mode, `OUTPUT.md` in bare mode) and selects the best based on correctness, code clarity, and minimal diff size. It responds with `{"winner": "<agent_id>"}`.

If only one worker succeeds, it is promoted directly — no judge call.

### Using variants with Claude, ChatGPT, and Gemini

The judge uses the same `provider` and `model` configured for planning. Set `default_variants` in config to apply variants to every run:

**Claude (Anthropic) — default:**

```json
{
  "provider": "anthropic",
  "model": "claude-opus-4-7",
  "default_variants": 3
}
```

```bash
export ANTHROPIC_API_KEY=sk-ant-...
aide run "Refactor the payment module" --variants 3
```

**ChatGPT (OpenAI):**

```json
{
  "provider": "openai",
  "model": "gpt-4o",
  "auth_mode": "api_key",
  "api_key_env": "OPENAI_API_KEY",
  "default_variants": 3
}
```

```bash
export OPENAI_API_KEY=sk-...
pip install -e '.[openai]'
aide run "Write unit tests for the billing service" --variants 3
```

**Gemini (Google):**

```json
{
  "provider": "google",
  "model": "gemini-2.0-flash",
  "auth_mode": "subscription",
  "default_variants": 3
}
```

```bash
gemini auth
pip install -e '.[google]'
aide run "Generate product descriptions" --variants 3
```

### Fallback behavior

| Situation | Result |
|-----------|--------|
| All N workers fail | Task marked failed, no judge called |
| Exactly 1 worker succeeds | Promoted directly, judge skipped |
| 2+ succeed, all pass verify | Judge selects among all passing |
| 2+ succeed, none pass verify | Judge selects among all that succeeded |
| Judge returns invalid JSON | First worker selected (silent fallback) |
| Judge names unknown agent | First worker selected (silent fallback) |
| Judge call throws exception | First worker selected, warning logged |

### Library usage

```python
from aide.models import Plan

# Set variants on the plan before running
plan = plan_task(task, provider="anthropic", model="claude-opus-4-7")
plan.variants = 3

result = await run_manager(
    plan,
    repo_path,
    taskbox,
    judge_provider="anthropic",   # LLM used to judge variants
    judge_model="claude-opus-4-7",
    verify_cmd="pytest tests/",
)
```

`judge_provider` and `judge_model` default to `"anthropic"` and the provider's default model when not specified. They are independent of the worker CLI — you can run Gemini workers and judge with Claude, or vice versa.

---

## Recipes

### Run Claude on a task, collect output

```bash
aide run "Summarize the key decisions in DECISIONS.md" \
  --agents 1 \
  --output ./summaries
cat summaries/.aide/runs/*/agent-*/OUTPUT.md
```

### Run GPT-4o as the worker

```bash
# .aide/config.json
{
  "provider": "openai",
  "model": "gpt-4o",
  "auth_mode": "api_key",
  "api_key_env": "OPENAI_API_KEY",
  "worker_cmd": "codex"
}
```

```bash
aide run "Write a blog post about async Python"
```

### Run Gemini as the worker

```bash
gemini auth
# .aide/config.json
{
  "provider": "google",
  "model": "gemini-2.0-flash",
  "auth_mode": "subscription",
  "worker_cmd": "gemini"
}
```

```bash
aide run "Generate 20 product name ideas for a smart water bottle"
```

### Parallel code review across a large PR

```bash
cd your-repo
aide run --file review-prompt.md --agents 8 --verify "pytest"
```

`review-prompt.md`:
```markdown
Review the changes in this PR for security vulnerabilities, performance issues, and test coverage gaps. Each agent should focus on a different module.
```

### Multi-agent content generation

```bash
# No git needed
aide run "Write 5 distinct landing page headlines for a B2B SaaS product \
  that helps engineering teams ship faster" --agents 5
```

Each agent produces its own `OUTPUT.md`. Browse results in `.aide/runs/<id>/`.

### Best-of-3 with Claude judge

```bash
# Run 3 workers per task; Claude picks the best implementation
aide run "Implement JWT refresh token rotation" \
  --variants 3 \
  --verify "pytest tests/auth/"
```

### Best-of-3 content generation with Gemini

```bash
# .aide/config.json
{
  "provider": "google",
  "model": "gemini-2.0-flash",
  "auth_mode": "subscription",
  "default_variants": 3
}
```

```bash
aide run "Write three distinct value propositions for our B2B SaaS"
# Gemini judges its own outputs; best one lands in OUTPUT.md
```

### Setting up a git repo from scratch

```bash
git init my-project
cd my-project
aide init
# answer prompts: provider, model, auth mode, workspace mode (auto or git)
echo ".aide/" >> .gitignore
git add .gitignore
git commit -m "chore: add .gitignore for AIDE"
aide run "Scaffold a FastAPI project with SQLAlchemy and alembic"
```

---

## How It Works

```
aide run "Add rate limiting to all API endpoints"
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
              Git mode:  each agent gets an isolated worktree on branch aide/<run>/<agent>
              Bare mode: each agent gets a temp dir under .aide/runs/<run>/<agent>
              --variants N: N agents race on the same task simultaneously
       │
       ▼
3. Execute — Each worker writes TASK.md into its workspace and spawns
             the agentic CLI (claude/codex/gemini) to complete the work.
       │
       ▼
3b. Judge (--variants N only) — After all N workers finish:
              Test gate: verify command filters failing outputs
              LLM judge: scores survivors, selects winner
              Winner proceeds to integration; others discarded
       │
       ▼
4. Integrate — When an agent finishes (or variant winner is selected):
               Git mode:  verify command runs → passing branches merge → dependents unlock
               Bare mode: output preserved at workspace path → dependents unlock
       │
       ▼
5. Report — aide status shows per-run and per-task outcomes.
            Bare mode also prints output_paths for each completed agent.
```

Key properties:

- **No shared state** — each agent has its own workspace; no file conflicts
- **DAG ordering** — tasks only start when all their dependencies complete
- **Automatic integration** — branches merged or outputs collected without manual work
- **Provider-agnostic** — swap planning LLM and worker CLI independently
- **Git-optional** — works for any agentic task, not just code

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
      ├── Workspace — slot lifecycle
      │    ├── GitWorkspace  — worktrees, branch creation, git merge
      │    └── BareWorkspace — temp dirs, no git
      ├── Workers (N subprocesses) — each spawns agentic CLI in isolated workspace
      └── Integration — verify → merge/collect → unlock dependents
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
  manager.py          # asyncio orchestrator — dispatch N variants, judge, integrate
  planner.py          # prompt → Plan (DAG of SubTasks + complexity score)
  worker.py           # async subprocess wrapper for agentic CLI; returns bool
  judge.py            # VariantCandidate, diff extraction, LLM judge selection
  workspace.py        # GitWorkspace, BareWorkspace, workspace_factory
  integration.py      # verify command + git merge
  taskbox.py          # SQLite message bus
  models.py           # Plan, SubTask, RunRecord, AgentRecord, Message
```

---

## Development

```bash
pip install -e '.[dev]'

pytest                              # all tests
pytest --ignore=tests/test_worker.py   # skip slow timeout test (~100s)
pytest tests/test_worker.py            # only the timeout test
```

---

## License

MIT
