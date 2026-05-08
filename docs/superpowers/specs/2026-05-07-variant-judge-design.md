# AIDE: Variant Workers + Judge Selection — Design Spec

**Date:** 2026-05-07
**Status:** Approved
**Feature:** `--variants N` flag — dispatch N workers per task, judge survivors, merge winner

---

## Overview

Add a `--variants N` option to `aide run`. When N > 1, each task dispatches N independent workers in parallel. A two-stage selection process (test gate → LLM judge) picks the best output. Only the winner is merged. When N = 1 (default), behavior is identical to today.

---

## Goals

1. Allow N workers to race on the same task
2. Test gate eliminates broken variants before judging
3. LLM judge scores survivors and selects the best
4. Winner merges via existing integration path
5. Works in both git and bare workspace modes

## Non-Goals

- Per-task variant count (all tasks in a run share the same N)
- Retry logic on judge failure
- Storing variant outputs for later inspection
- Changing the planner, taskbox schema, or workspace modules

---

## Architecture

### Flow

```
--variants 1 (default):
  task → _dispatch(1 worker) → COMPLETE → verify → merge

--variants N:
  task → _dispatch(N workers) ──────────────────────────────────────────┐
                              wait for all N (asyncio.gather)            │
                              ↓                                          │
                         0 complete → ERROR (task failed)               │
                         1 complete → verify → merge (skip judge)       │
                         N complete → run_verify each                   │
                                    → 0 pass verify: judge all N        │
                                    → 1 passes: merge directly          │
                                    → 2+ pass: judge survivors → merge  │
                                    ↓                                    │
                              workspace.integrate(winner)               │
                              send COMPLETE or ERROR to manager ─────────┘
```

**Key invariant:** Manager loop sees exactly one COMPLETE or ERROR per task regardless of N. Manager loop body is unchanged.

### New Components

| Component | Location | Purpose |
|-----------|----------|---------|
| `VariantCandidate` dataclass | `aide/judge.py` | Holds agent_id, slot_path, branch for one variant |
| `select_winner()` | `aide/judge.py` | LLM judge — picks best candidate from list |
| `_get_diff()` | `aide/judge.py` | Extracts diff (git mode) or OUTPUT.md (bare mode) |
| `Plan.variants` | `aide/models.py` | Int field, default 1 |
| `--variants` CLI flag | `aide/cli.py` | Passed to `run_manager()` → `Plan` |

### Unchanged Components

`planner.py`, `taskbox.py`, `workspace.py`, `integration.py`, manager loop body

---

## Data Models

### `Plan` (models.py)

```python
@dataclass
class Plan:
    run_id: str
    original_prompt: str
    agent_count: int
    complexity_score: int
    tasks: list[SubTask]
    variants: int = 1          # new field
```

No SQLite schema changes. `variants` is not persisted — it's a runtime parameter.

### `VariantCandidate` (judge.py)

```python
@dataclass
class VariantCandidate:
    agent_id: str
    slot_path: Path
    branch: str          # git mode: branch name; bare mode: slot_id
```

Not persisted. Lives only during `_dispatch` execution.

---

## Manager Changes (manager.py)

### `run_worker()` return value

`run_worker()` gains a `bool` return value: `True` = worker sent COMPLETE, `False` = ERROR, timeout, or exception. Timeout explicitly returns `False` (the existing `proc.kill()` + early return path). All existing message sending to Taskbox is preserved.

### `_dispatch()` — N-worker variant

```python
async def _dispatch(subtask) -> None:
    # Spawn N slots and N workers
    slots = []
    worker_coros = []
    for _ in range(plan.variants):
        agent_id = f"agent-{str(uuid.uuid4())[:6]}"
        slot_path, slot_id = workspace.create_slot(plan.run_id, agent_id)
        taskbox.save_agent(AgentRecord(...))
        taskbox.update_task_status(subtask.id, "in_progress", ...)
        slots.append((agent_id, slot_path, slot_id))
        worker_coros.append(run_worker(agent_id=agent_id, ...))

    async with semaphore:
        results = await asyncio.gather(*worker_coros)

    # Filter to workers that completed successfully
    successes = [slots[i] for i, ok in enumerate(results) if ok]

    if not successes:
        taskbox.send_message(Message(type="ERROR", payload={"task_id": subtask.id}, ...))
        return

    if len(successes) == 1:
        winner_agent, winner_path, winner_branch = successes[0]
    else:
        # Two-stage: verify each, judge among survivors
        passing = [
            (a, p, b) for a, p, b in successes
            if run_verify(p, verify_cmd)[0]
        ]
        pool = passing if passing else successes  # fallback: judge all if none pass
        if len(pool) == 1:
            winner_agent, winner_path, winner_branch = pool[0]
        else:
            candidates = [VariantCandidate(a, p, b) for a, p, b in pool]
            winner = judge.select_winner(subtask.description, candidates, workspace,
                                         provider=provider, model=model)
            winner_agent, winner_path, winner_branch = winner.agent_id, winner.slot_path, winner.branch

    ok, _ = workspace.integrate(winner_path, winner_branch, verify_cmd)
    # _ (merge output string) intentionally discarded — only ok matters for routing
    msg_type = "COMPLETE" if ok else "ERROR"
    taskbox.send_message(Message(type=msg_type, payload={"task_id": subtask.id}, ...))
```

**Semaphore note:** `async with semaphore` acquires **one slot** for the entire `asyncio.gather` block — not one slot per worker subprocess. The gather starts all N subprocesses concurrently within that single acquired slot, then releases when all N finish. With `max_concurrent=20` and `variants=3`, up to 20 tasks run concurrently (each spawning up to 3 subprocesses = 60 total worker processes). The semaphore bounds task-level parallelism, not subprocess count. If per-subprocess limiting is needed in the future, move `async with semaphore` inside each worker coroutine.

---

## Judge Module (aide/judge.py)

### `select_winner()`

```python
def select_winner(
    task_description: str,                  # positional 1: task context for judge prompt
    candidates: list[VariantCandidate],     # positional 2: variants to compare
    workspace: GitWorkspace | BareWorkspace, # positional 3: used for diff extraction
    provider: str = "anthropic",            # keyword: LLM provider name
    model: str | None = None,              # keyword: None → provider default_model
) -> VariantCandidate:
```

All callers must pass the first three arguments positionally in this order. `provider` and `model` must always be passed as keyword arguments. Returns one `VariantCandidate`. Falls back to `candidates[0]` on any judge failure.

### Diff extraction

- **Git mode:** `git diff <base>..<branch>` — patch text
- **Bare mode:** contents of `OUTPUT.md` in the slot dir

### Judge prompt

```
Task: <task_description>

You are selecting the best implementation from N candidates.
Criteria: correctness, code clarity, minimal diff size.

[Candidate <agent_id_1>]
<diff or output>

[Candidate <agent_id_2>]
<diff or output>

Respond ONLY with valid JSON: {"winner": "<agent_id>"}
```

Uses existing `get_provider(provider).generate()`. No new provider API surface. If `provider` is not in `SUPPORTED_PROVIDERS`, raises `ValueError` (same behavior as `planner.plan_task()`). If `model` is `None`, the provider's `default_model` from `SUPPORTED_PROVIDERS` is used.

### Fallback behavior

| Failure | Fallback |
|---------|----------|
| Judge LLM returns invalid JSON | `candidates[0]` |
| Judge names unknown agent_id | `candidates[0]` |
| Judge call raises exception | `candidates[0]`, log warning |

---

## CLI Changes (cli.py)

```bash
aide run "prompt" --variants 3
```

New option on `run` command:

```python
@click.option("--variants", type=int, default=None,
              help="Workers per task (default: 1, or config default_variants)")
```

Resolution order: CLI flag → `config.get("default_variants")` → `1`. If `default_variants` is absent from config (e.g., existing install pre-dating this feature), the missing key is safe — `dict.get()` returns `None`, which falls through to the hardcoded default of `1`.

Config key `"default_variants": 1` added to the `.aide/config.json` template written by `init_aide()`. Existing installs are not migrated automatically — the `init_aide()` guard (`if not config_path.exists()`) skips the write if config already exists. Existing installs without the key fall back to `1` safely via `config.get()`.

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| All N workers error | Task → `failed`; no judge called |
| All N complete, none pass verify | Judge called on all N (unverified); winner merged; if merge fails → `failed` |
| Judge returns bad JSON | Warning logged; `candidates[0]` selected |
| Judge names unknown agent_id | Warning logged; `candidates[0]` selected |
| `--variants 1` | `_dispatch` path identical to today; judge never called |
| Semaphore with high N | Existing semaphore handles; all N workers for a task share one slot |

---

## Testing

### New test file

**`tests/test_judge.py`**
- `select_winner()` with mocked provider — returns valid JSON
- `select_winner()` fallback on invalid JSON
- `select_winner()` fallback on unknown agent_id
- Diff extraction: git mode (mock subprocess) and bare mode (write OUTPUT.md)

### Modified test files

**`tests/test_worker.py`**
- All existing tests updated to assert return value (`True`/`False`)
- Success → returns `True`
- Failure/timeout → returns `False`

**`tests/test_manager.py`**
- `variants=3`, all workers succeed → judge called, winner merged
- `variants=3`, 1 worker succeeds → judge skipped, winner merged directly
- `variants=3`, all workers fail → task marked failed
- `variants=3`, multiple pass verify → judge called among passers only
- `variants=1` → behavior identical to existing tests

**`tests/test_cli.py`**
- `--variants 3` passed through to `run_manager()`
- `default_variants` from config used when flag absent

### Unchanged test files

`test_taskbox.py`, `test_workspace.py`, `test_integration.py`, `test_planner.py`, `test_models.py`

---

## File Map

| File | Change |
|------|--------|
| `aide/models.py` | Add `Plan.variants: int = 1` |
| `aide/worker.py` | Add `-> bool` return value |
| `aide/manager.py` | `_dispatch()` spawns N workers, runs judge flow |
| `aide/judge.py` | New file: `VariantCandidate`, `select_winner()`, `_get_diff()` |
| `aide/cli.py` | Add `--variants` option; pass to `run_manager()` |
| `aide/workspace.py` | Add `"default_variants": 1` to `init_aide()` config template |
| `tests/test_judge.py` | New file |
| `tests/test_worker.py` | Assert bool return |
| `tests/test_manager.py` | Variant dispatch tests |
| `tests/test_cli.py` | `--variants` flag tests |

---

## Success Criteria

- `aide run "prompt" --variants 1` behavior identical to current
- `aide run "prompt" --variants 3` spawns 3 workers per task, merges best
- Judge is skipped when only one worker completes or passes verify
- Judge fallback fires silently on bad LLM response
- All existing tests pass unchanged
- New tests cover judge selection, fallback, and manager variant paths
