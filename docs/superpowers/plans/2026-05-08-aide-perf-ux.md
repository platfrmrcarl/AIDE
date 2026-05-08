# AIDE Performance + UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 50ms SQLite poll loop with an asyncio.Queue, refactor the CLI to async with a rich spinner, add live progress streaming, per-task completion callbacks, a rich output table, and an `aide rerun` command.

**Architecture:** `_dispatch` puts COMPLETE/ERROR events directly onto an `asyncio.Queue` — manager `await`s it instead of polling every 50ms. CLI `run` becomes an async function so a rich spinner can animate during planning. All UX improvements (streaming, completion callbacks, table) are threaded through run_manager/run_worker via optional callback params.

**Tech Stack:** Python 3.11+, asyncio, `rich>=13.0` (new dep), existing SQLite Taskbox (PROGRESS messages stay there, COMPLETE/ERROR move to queue)

---

## File Map

| File | Change |
|------|--------|
| `pyproject.toml` | Add `rich>=13.0` to dependencies |
| `aide/taskbox.py` | WAL mode in `_conn()`; `INSERT OR IGNORE` in `save_task()`; add `reset_failed_tasks()` |
| `aide/worker.py` | Add `progress_callback` param |
| `aide/manager.py` | asyncio.Queue replaces poll; `on_task_complete` callback; `stream_output` param; pre-populate completed |
| `aide/cli.py` | Async `run` + spinner; rich output table; `rerun` command |
| `tests/test_taskbox.py` | WAL mode test; `reset_failed_tasks` test |
| `tests/test_worker.py` | `progress_callback` test |
| `tests/test_manager.py` | Queue-based tests; `on_task_complete` tests |
| `tests/test_cli.py` | `rerun` tests; spinner non-crash test; rich table test |

---

## Task 1: asyncio.Queue event loop + SQLite WAL mode

**Files:**
- Modify: `aide/taskbox.py`
- Modify: `aide/manager.py`
- Modify: `tests/test_taskbox.py`
- Modify: `tests/test_manager.py`

The 50ms `asyncio.sleep(0.05)` poll causes up to 50ms latency between wave completions. Replace with `asyncio.Queue` — `_dispatch` puts one event per task, manager `await`s it. WAL mode bundled here since it's also a Taskbox change.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_taskbox.py`:

```python
def test_taskbox_uses_wal_mode(tmp_path):
    db = Taskbox(tmp_path / "aide.db")
    with db._conn() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"
```

Run: `pytest tests/test_taskbox.py::test_taskbox_uses_wal_mode -v`
Expected: FAIL — `assert 'delete' == 'wal'`

- [ ] **Step 2: Add WAL mode to Taskbox._conn()**

In `aide/taskbox.py`, replace `_conn`:

```python
def _conn(self) -> sqlite3.Connection:
    conn = sqlite3.connect(self.db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn
```

Run: `pytest tests/test_taskbox.py::test_taskbox_uses_wal_mode -v`
Expected: PASS

- [ ] **Step 3: Change save_task to INSERT OR IGNORE**

In `aide/taskbox.py`, in `save_task`, change `INSERT OR REPLACE` to `INSERT OR IGNORE`:

```python
def save_task(self, task: SubTask, run_id: str) -> None:
    now = datetime.utcnow().isoformat()
    with self._conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                task.id, run_id, task.description, json.dumps(task.depends_on),
                task.assigned_agent, task.status, task.worktree_path, task.branch,
                now, now,
            ),
        )
```

- [ ] **Step 4: Write queue-based manager tests**

The existing manager tests mock `run_worker` returning `True`/`False` and `workspace.integrate`. With the queue replacing SQLite routing, these tests should still pass without changes — the queue is internal. Verify:

```bash
pytest tests/test_manager.py -v
```

Expected: All existing tests pass (queue is transparent to tests that mock run_worker and workspace).

If any fail, it's because they assert on SQLite COMPLETE messages — remove those assertions and assert on `result["status"]` instead.

- [ ] **Step 5: Rewrite aide/manager.py with asyncio.Queue**

Replace `aide/manager.py` in full:

```python
import asyncio
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import judge
from .integration import run_verify
from .models import AgentRecord, Message, Plan, RunRecord
from .taskbox import Taskbox
from .worker import run_worker
from .workspace import workspace_factory


async def run_manager(
    plan: Plan,
    repo_path: Path,
    taskbox: Taskbox,
    max_concurrent: int = 20,
    verify_cmd: str | None = None,
    worker_cmd: str = "auto",
    worker_timeout: int = 120,
    mode: str = "auto",
    output_dir: Path | None = None,
    judge_provider: str = "anthropic",
    judge_model: str | None = None,
    on_task_complete: Callable[[str, str, str], None] | None = None,
    stream_output: bool = False,
) -> dict:
    workspace = workspace_factory({"mode": mode}, repo_path, output_dir)
    worker_mode = workspace.mode

    taskbox.save_run(
        RunRecord(
            id=plan.run_id,
            prompt=plan.original_prompt,
            agent_count=plan.agent_count,
            complexity_score=plan.complexity_score,
        )
    )
    for task in plan.tasks:
        taskbox.save_task(task, plan.run_id)

    all_ids = {t.id for t in plan.tasks}
    # Pre-populate completed so rerun skips already-done tasks
    completed: set[str] = {
        t.id for t in taskbox.get_tasks(plan.run_id) if t.status == "complete"
    }
    failed: set[str] = set()
    in_flight: dict[str, asyncio.Task] = {}
    output_paths: list[str] = []
    result_queue: asyncio.Queue[dict] = asyncio.Queue()
    semaphore = asyncio.Semaphore(max_concurrent)

    subtask_map = {t.id: t for t in plan.tasks}

    def _progress_cb(agent_id: str, line: str) -> None:
        if stream_output:
            print(f"  [{agent_id}] {line}", file=sys.stderr, flush=True)

    async def _dispatch(subtask) -> None:
        try:
            slots: list[tuple[str, Path, str]] = []
            worker_coros = []

            for _ in range(plan.variants):
                agent_id = f"agent-{str(uuid.uuid4())[:6]}"
                slot_path, slot_id = workspace.create_slot(plan.run_id, agent_id)
                taskbox.save_agent(
                    AgentRecord(
                        id=agent_id, run_id=plan.run_id,
                        worktree_path=str(slot_path), branch=slot_id,
                        task_id=subtask.id, last_heartbeat=datetime.utcnow(),
                    )
                )
                slots.append((agent_id, slot_path, slot_id))
                worker_coros.append(
                    run_worker(
                        agent_id=agent_id, run_id=plan.run_id,
                        task_id=subtask.id, task_description=subtask.description,
                        worktree_path=slot_path, taskbox=taskbox,
                        timeout=worker_timeout, worker_cmd=worker_cmd,
                        mode=worker_mode, silent=True,
                        progress_callback=_progress_cb,
                    )
                )

            taskbox.update_task_status(
                subtask.id, "in_progress",
                assigned_agent=slots[0][0],
                worktree_path=str(slots[0][1]),
                branch=slots[0][2],
            )

            async with semaphore:
                results: list[bool] = list(await asyncio.gather(*worker_coros))

            successes = [slots[i] for i, ok in enumerate(results) if ok]

            if not successes:
                await result_queue.put({"type": "ERROR", "task_id": subtask.id,
                                        "description": subtask.description})
                return

            if len(successes) == 1:
                winner_agent, winner_path, winner_branch = successes[0]
            else:
                passing = [
                    (a, p, b) for a, p, b in successes
                    if run_verify(p, verify_cmd)[0]
                ]
                pool = passing if passing else successes
                if len(pool) == 1:
                    winner_agent, winner_path, winner_branch = pool[0]
                else:
                    candidates = [
                        judge.VariantCandidate(agent_id=a, slot_path=p, branch=b)
                        for a, p, b in pool
                    ]
                    w = judge.select_winner(
                        subtask.description, candidates, workspace,
                        provider=judge_provider, model=judge_model,
                    )
                    winner_agent = w.agent_id
                    winner_path = w.slot_path
                    winner_branch = w.branch

            taskbox.update_task_status(
                subtask.id, "in_progress",
                assigned_agent=winner_agent,
                worktree_path=str(winner_path),
                branch=winner_branch,
            )
            await result_queue.put({
                "type": "COMPLETE",
                "task_id": subtask.id,
                "winner_path": str(winner_path),
                "winner_branch": winner_branch,
                "description": subtask.description,
            })

        except Exception as exc:
            await result_queue.put({
                "type": "ERROR",
                "task_id": subtask.id,
                "description": subtask_map.get(subtask.id, subtask).description,
                "error": str(exc),
            })

    while len(completed) + len(failed) < len(all_ids):
        # Dispatch all newly-available tasks
        dispatchable = [
            t for t in plan.tasks
            if t.id not in completed
            and t.id not in failed
            and t.id not in in_flight
            and all(dep in completed for dep in t.depends_on)
        ]
        for subtask in dispatchable:
            in_flight[subtask.id] = asyncio.create_task(_dispatch(subtask))

        # Cascade failures for tasks whose dependencies failed
        for task in plan.tasks:
            if (
                task.id not in completed
                and task.id not in failed
                and task.id not in in_flight
                and any(dep in failed for dep in task.depends_on)
            ):
                failed.add(task.id)
                taskbox.update_task_status(task.id, "failed")

        if len(completed) + len(failed) >= len(all_ids):
            break
        if not in_flight:
            break  # nothing running and nothing dispatchable — deadlock guard

        # Wait for next result — no polling, no sleep
        event = await result_queue.get()
        task_id = event["task_id"]
        desc = event.get("description", "")

        if event["type"] == "COMPLETE":
            winner_path = Path(event["winner_path"])
            winner_branch = event["winner_branch"]
            ok, _out = workspace.integrate(winner_path, winner_branch, verify_cmd)
            if ok:
                completed.add(task_id)
                taskbox.update_task_status(task_id, "complete")
                if worker_mode == "bare":
                    output_paths.append(event["winner_path"])
                if on_task_complete:
                    on_task_complete(task_id, "complete", desc)
            else:
                failed.add(task_id)
                taskbox.update_task_status(task_id, "failed")
                if on_task_complete:
                    on_task_complete(task_id, "failed", desc)

        elif event["type"] == "ERROR":
            failed.add(task_id)
            taskbox.update_task_status(task_id, "failed")
            if on_task_complete:
                on_task_complete(task_id, "failed", desc)

        in_flight.pop(task_id, None)

    status = "complete" if not failed else "failed"
    taskbox.save_run(
        RunRecord(
            id=plan.run_id,
            prompt=plan.original_prompt,
            agent_count=plan.agent_count,
            complexity_score=plan.complexity_score,
            status=status,
            completed_at=datetime.utcnow(),
        )
    )

    result: dict = {
        "run_id": plan.run_id,
        "status": status,
        "completed": len(completed),
        "failed": len(failed),
        "total": len(all_ids),
    }
    if worker_mode == "bare":
        result["output_paths"] = output_paths
    return result
```

- [ ] **Step 6: Run all manager tests**

```bash
pytest tests/test_manager.py -v
```

Expected: all pass

- [ ] **Step 7: Run full suite**

```bash
pytest tests/ -v
```

Expected: all pass

- [ ] **Step 8: Commit**

```bash
git add aide/taskbox.py aide/manager.py tests/test_taskbox.py tests/test_manager.py
git commit -m "perf: replace SQLite poll loop with asyncio.Queue; WAL mode on Taskbox"
```

---

## Task 2: add rich + async CLI + spinner during planning

**Files:**
- Modify: `pyproject.toml`
- Modify: `aide/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Add rich to pyproject.toml**

In `pyproject.toml`, add `"rich>=13.0"` to `dependencies`:

```toml
dependencies = [
    "anthropic>=0.40.0",
    "click>=8.0",
    "httpx>=0.27",
    "rich>=13.0",
]
```

Install:

```bash
pip install rich>=13.0
```

- [ ] **Step 2: Write failing test**

Add to `tests/test_cli.py`:

```python
def test_run_planning_spinner_does_not_crash(runner, git_repo, mocker):
    """Spinner is disabled in non-TTY (test) environments; run completes normally."""
    init_aide(git_repo)
    mocker.patch("aide.cli.plan_task", return_value=_simple_plan())
    mocker.patch("aide.cli.run_manager", new=AsyncMock(return_value={
        "run_id": "abc123", "status": "complete", "completed": 1, "failed": 0, "total": 1,
    }))
    result = runner.invoke(main, ["run", "do stuff", "--repo", str(git_repo)])
    assert result.exit_code == 0, result.output
```

Run: `pytest tests/test_cli.py::test_run_planning_spinner_does_not_crash -v`
Expected: PASS (existing sync CLI already works; this test validates the post-refactor async CLI also passes)

- [ ] **Step 3: Refactor aide/cli.py run command to async with spinner**

Replace the `run` command in `aide/cli.py`. The function body moves into `_run_async`; the Click handler just calls `asyncio.run(_run_async(...))`. Add spinner wrapping `plan_task()` via `asyncio.to_thread`.

Full new `run` command (replace existing `run` function completely):

```python
@main.command()
@click.argument("prompt", required=False)
@click.option("--file", "-f", "task_file", type=click.Path(exists=True))
@click.option("--repo", default=".", type=click.Path())
@click.option("--agents", type=int, default=None)
@click.option("--verify", "verify_cmd", default=None)
@click.option("--output", "output_dir", default=None, type=click.Path(),
              help="Output directory for bare mode agent results.")
@click.option("--variants", type=int, default=None,
              help="Workers per task for variant selection (default: 1)")
def run(prompt, task_file, repo, agents, verify_cmd, output_dir, variants):
    """Run agents on a task prompt or .md file."""
    if prompt and task_file:
        click.echo("Error: provide either a prompt or --file, not both.")
        raise SystemExit(1)
    if not prompt and not task_file:
        click.echo("Error: provide a prompt or --file.", err=True)
        raise SystemExit(1)
    asyncio.run(_run_async(prompt, task_file, repo, agents, verify_cmd, output_dir, variants))


async def _run_async(prompt, task_file, repo, agents, verify_cmd, output_dir, variants):
    from rich.progress import Progress, SpinnerColumn, TextColumn
    import sys

    repo_path = Path(repo).resolve()

    if not is_initialized(repo_path):
        init_aide(repo_path)

    if task_file:
        prompt = Path(task_file).read_text()

    config = get_config(repo_path)

    in_tty = sys.stderr.isatty()
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]Planning..."),
        disable=not in_tty,
        transient=True,
    ) as progress:
        progress.add_task("")
        plan = await asyncio.to_thread(
            plan_task,
            prompt,
            provider=config.get("provider", "anthropic"),
            model=config.get("model"),
            auth_mode=config.get("auth_mode", "auto"),
            api_key_env=config.get("api_key_env"),
            agent_count_override=agents,
        )

    resolved_variants = variants if variants is not None else config.get("default_variants", 1)
    plan.variants = resolved_variants

    taskbox = Taskbox(repo_path / ".aide" / "aide.db")

    result = await run_manager(
        plan,
        repo_path,
        taskbox,
        max_concurrent=config.get("max_concurrent_workers", 20),
        verify_cmd=verify_cmd or config.get("verify_command"),
        worker_cmd=config.get("worker_cmd", "auto"),
        worker_timeout=config.get("worker_timeout_seconds", 120),
        mode=config.get("mode", "auto"),
        output_dir=Path(output_dir) if output_dir else None,
        judge_provider=config.get("provider", "anthropic"),
        judge_model=config.get("model"),
        on_task_complete=_make_completion_cb(in_tty),
        stream_output=False,
    )

    _print_run_table(result, taskbox, plan.run_id)


def _make_completion_cb(verbose: bool):
    if not verbose:
        return None
    def _cb(task_id: str, status: str, desc: str) -> None:
        icon = "✓" if status == "complete" else "✗"
        click.echo(f"  {icon} {task_id}: {desc[:70]}", err=False)
    return _cb


def _print_run_table(result: dict, taskbox: "Taskbox", run_id: str) -> None:
    from rich.console import Console
    from rich.table import Table

    console = Console()
    tasks = taskbox.get_tasks(run_id)

    table = Table(title=f"Run {result['run_id']}  •  {result['status']}", show_lines=False)
    table.add_column("Task", style="dim", width=6)
    table.add_column("Status", width=10)
    table.add_column("Description")

    for t in tasks:
        icon = "✓" if t.status == "complete" else ("✗" if t.status == "failed" else "·")
        color = "green" if t.status == "complete" else ("red" if t.status == "failed" else "yellow")
        table.add_row(t.id, f"[{color}]{icon} {t.status}[/{color}]", t.description[:80])

    console.print(table)
    for path in result.get("output_paths", []):
        console.print(f"  [dim]→[/dim] {path}")
```

Also add the import `from rich.console import Console` and `from rich.table import Table` is handled inline above. No top-level import needed.

- [ ] **Step 4: Run all CLI tests**

```bash
pytest tests/test_cli.py -v
```

Expected: all pass (including new spinner test)

- [ ] **Step 5: Run full suite**

```bash
pytest tests/ -v
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml aide/cli.py tests/test_cli.py
git commit -m "feat: async CLI run with rich spinner during planning; rich output table"
```

---

## Task 3: Live stdout streaming callback

**Files:**
- Modify: `aide/worker.py`
- Modify: `tests/test_worker.py`

`run_worker` currently sends PROGRESS to SQLite only. Add a `progress_callback(agent_id, line)` param so callers can also receive lines in real time.

- [ ] **Step 1: Write failing test**

Add to `tests/test_worker.py`:

```python
@pytest.mark.asyncio
async def test_worker_progress_callback_called(db, tmp_path):
    make_agent(db, tmp_path)
    received: list[tuple[str, str]] = []

    def _cb(agent_id: str, line: str) -> None:
        received.append((agent_id, line))

    # Use a worker_cmd that prints to stdout then exits 0
    script = tmp_path / "echo_worker.sh"
    script.write_text("#!/bin/sh\necho 'hello from agent'\n")
    script.chmod(script.stat().st_mode | 0o111)

    await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, worker_cmd=str(script),
        progress_callback=_cb,
    )

    assert any("hello from agent" in line for _, line in received)
    assert all(agent_id == "a1" for agent_id, _ in received)


@pytest.mark.asyncio
async def test_worker_no_callback_still_works(db, tmp_path):
    make_agent(db, tmp_path)
    result = await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, worker_cmd="true",
    )
    assert result is True
```

Run: `pytest tests/test_worker.py::test_worker_progress_callback_called tests/test_worker.py::test_worker_no_callback_still_works -v`
Expected: FAIL — `run_worker` has no `progress_callback` param

- [ ] **Step 2: Add progress_callback to run_worker**

In `aide/worker.py`, add `progress_callback` param and call it in `_drain_stdout`:

```python
async def run_worker(
    agent_id: str,
    run_id: str,
    task_id: str,
    task_description: str,
    worktree_path: Path,
    taskbox: Taskbox,
    timeout: int = 120,
    worker_cmd: str = "auto",
    mode: Literal["git", "bare"] = "git",
    silent: bool = False,
    progress_callback: "Callable[[str, str], None] | None" = None,
) -> bool:
```

Add `from typing import Callable` to imports.

In `_drain_stdout`, after the `taskbox.send_message(...)` call:

```python
async def _drain_stdout() -> None:
    assert proc.stdout
    async for line in proc.stdout:
        decoded = line.decode().rstrip()
        taskbox.send_message(
            Message(
                id=str(uuid.uuid4()),
                type="PROGRESS",
                from_agent=agent_id,
                to_agent="manager",
                payload={"line": decoded},
                created_at=datetime.utcnow(),
            )
        )
        if progress_callback is not None:
            progress_callback(agent_id, decoded)
```

- [ ] **Step 3: Run all worker tests**

```bash
pytest tests/test_worker.py -v
```

Expected: all pass

- [ ] **Step 4: Commit**

```bash
git add aide/worker.py tests/test_worker.py
git commit -m "feat: add progress_callback to run_worker for live stdout streaming"
```

---

## Task 4: Per-task completion callback + on_task_complete wiring

**Files:**
- Modify: `tests/test_manager.py`

`run_manager` already has `on_task_complete` wired in Task 1. This task adds tests and validates the wiring.

- [ ] **Step 1: Write failing tests**

Add to `tests/test_manager.py`:

```python
@pytest.mark.asyncio
async def test_manager_on_task_complete_called_on_success(db, tmp_path):
    plan = _make_plan()
    ws = _make_mock_workspace(tmp_path)
    completed_calls: list[tuple[str, str, str]] = []

    def _cb(task_id, status, desc):
        completed_calls.append((task_id, status, desc))

    with patch("aide.manager.workspace_factory", return_value=ws), \
         patch("aide.manager.run_worker", new_callable=AsyncMock, return_value=True):
        result = await run_manager(plan, tmp_path, db, on_task_complete=_cb)

    assert result["status"] == "complete"
    assert len(completed_calls) == 1
    assert completed_calls[0][0] == "t1"
    assert completed_calls[0][1] == "complete"


@pytest.mark.asyncio
async def test_manager_on_task_complete_called_on_failure(db, tmp_path):
    plan = _make_plan()
    ws = _make_mock_workspace(tmp_path, integrate_result=(False, "tests failed"))
    failed_calls: list[tuple[str, str, str]] = []

    def _cb(task_id, status, desc):
        failed_calls.append((task_id, status, desc))

    with patch("aide.manager.workspace_factory", return_value=ws), \
         patch("aide.manager.run_worker", new_callable=AsyncMock, return_value=True):
        result = await run_manager(plan, tmp_path, db, on_task_complete=_cb)

    assert result["status"] == "failed"
    assert any(status == "failed" for _, status, _ in failed_calls)


@pytest.mark.asyncio
async def test_manager_no_callback_still_works(db, tmp_path):
    plan = _make_plan()
    ws = _make_mock_workspace(tmp_path)
    with patch("aide.manager.workspace_factory", return_value=ws), \
         patch("aide.manager.run_worker", new_callable=AsyncMock, return_value=True):
        result = await run_manager(plan, tmp_path, db)
    assert result["status"] == "complete"
```

Run: `pytest tests/test_manager.py -k "on_task_complete or no_callback" -v`
Expected: PASS (on_task_complete is already wired in Task 1's manager rewrite)

- [ ] **Step 2: Run full manager tests**

```bash
pytest tests/test_manager.py -v
```

Expected: all pass

- [ ] **Step 3: Commit**

```bash
git add tests/test_manager.py
git commit -m "test: on_task_complete callback coverage for run_manager"
```

---

## Task 5: aide rerun command

**Files:**
- Modify: `aide/taskbox.py`
- Modify: `aide/cli.py`
- Modify: `tests/test_taskbox.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_taskbox.py`:

```python
def test_reset_failed_tasks(db, tmp_path):
    from aide.models import SubTask
    from aide.workspace import init_aide
    init_aide(tmp_path)
    run_id = "r1"
    task = SubTask(id="t1", description="thing", depends_on=[])
    db.save_task(task, run_id)
    db.update_task_status("t1", "failed")

    db.reset_failed_tasks(run_id)

    tasks = db.get_tasks(run_id)
    assert tasks[0].status == "pending"


def test_reset_failed_tasks_leaves_complete_untouched(db, tmp_path):
    from aide.models import SubTask
    from aide.workspace import init_aide
    init_aide(tmp_path)
    run_id = "r1"
    for tid, status in [("t1", "complete"), ("t2", "failed")]:
        task = SubTask(id=tid, description="thing", depends_on=[])
        db.save_task(task, run_id)
        db.update_task_status(tid, status)

    db.reset_failed_tasks(run_id)

    tasks = {t.id: t for t in db.get_tasks(run_id)}
    assert tasks["t1"].status == "complete"
    assert tasks["t2"].status == "pending"
```

Add to `tests/test_cli.py`:

```python
def test_rerun_runs_failed_tasks(runner, git_repo, mocker):
    init_aide(git_repo)
    from aide.taskbox import Taskbox
    from aide.models import RunRecord, SubTask
    from datetime import datetime

    taskbox = Taskbox(git_repo / ".aide" / "aide.db")
    run_id = "abc123"
    taskbox.save_run(RunRecord(
        id=run_id, prompt="do stuff", agent_count=1, complexity_score=5,
        started_at=datetime(2026, 1, 1),
    ))
    task = SubTask(id="t1", description="Do a thing", depends_on=[])
    taskbox.save_task(task, run_id)
    taskbox.update_task_status("t1", "failed")

    mock_mgr = mocker.patch("aide.cli.run_manager", new=AsyncMock(return_value={
        "run_id": run_id, "status": "complete", "completed": 1, "failed": 0, "total": 1,
    }))

    result = runner.invoke(main, ["rerun", "--run-id", run_id, "--repo", str(git_repo)])
    assert result.exit_code == 0, result.output
    mock_mgr.assert_called_once()


def test_rerun_exits_when_run_not_found(runner, git_repo):
    init_aide(git_repo)
    result = runner.invoke(main, ["rerun", "--run-id", "notexist", "--repo", str(git_repo)])
    assert result.exit_code == 1
    assert "not found" in result.output.lower()


def test_rerun_exits_when_no_failed_tasks(runner, git_repo, mocker):
    init_aide(git_repo)
    from aide.taskbox import Taskbox
    from aide.models import RunRecord, SubTask
    from datetime import datetime

    taskbox = Taskbox(git_repo / ".aide" / "aide.db")
    run_id = "abc123"
    taskbox.save_run(RunRecord(
        id=run_id, prompt="do stuff", agent_count=1, complexity_score=5,
        started_at=datetime(2026, 1, 1),
    ))
    task = SubTask(id="t1", description="Do a thing", depends_on=[])
    taskbox.save_task(task, run_id)
    taskbox.update_task_status("t1", "complete")

    result = runner.invoke(main, ["rerun", "--run-id", run_id, "--repo", str(git_repo)])
    assert result.exit_code == 0
    assert "no failed" in result.output.lower()
```

Run: `pytest tests/test_taskbox.py -k "reset_failed" tests/test_cli.py -k "rerun" -v`
Expected: FAIL — `reset_failed_tasks` not defined; `rerun` command not defined

- [ ] **Step 2: Add reset_failed_tasks to Taskbox**

Add to `aide/taskbox.py` after `get_completed_task_ids`:

```python
def reset_failed_tasks(self, run_id: str) -> int:
    """Reset all failed tasks for a run back to pending. Returns count reset."""
    with self._conn() as conn:
        cursor = conn.execute(
            "UPDATE tasks SET status='pending', updated_at=? WHERE run_id=? AND status='failed'",
            (datetime.utcnow().isoformat(), run_id),
        )
        return cursor.rowcount
```

- [ ] **Step 3: Add rerun command to aide/cli.py**

Add after the `run` command (before `status`):

```python
@main.command()
@click.option("--run-id", required=True, help="ID of the run to retry.")
@click.option("--repo", default=".", type=click.Path())
def rerun(run_id, repo):
    """Retry failed tasks from a previous run."""
    repo_path = Path(repo).resolve()
    taskbox = Taskbox(repo_path / ".aide" / "aide.db")

    run_rec = taskbox.get_run(run_id)
    if not run_rec:
        click.echo(f"Run {run_id} not found.")
        raise SystemExit(1)

    tasks = taskbox.get_tasks(run_id)
    failed = [t for t in tasks if t.status == "failed"]
    if not failed:
        click.echo(f"No failed tasks in run {run_id}.")
        return

    taskbox.reset_failed_tasks(run_id)
    click.echo(f"Retrying {len(failed)} failed task(s) from run {run_id}.")

    from .models import Plan
    config = get_config(repo_path) if is_initialized(repo_path) else {}
    plan = Plan(
        run_id=run_id,
        original_prompt=run_rec.prompt,
        agent_count=run_rec.agent_count,
        complexity_score=run_rec.complexity_score,
        tasks=tasks,
    )

    asyncio.run(_rerun_async(plan, repo_path, taskbox, config))


async def _rerun_async(plan, repo_path: Path, taskbox: "Taskbox", config: dict) -> None:
    result = await run_manager(
        plan,
        repo_path,
        taskbox,
        max_concurrent=config.get("max_concurrent_workers", 20),
        verify_cmd=config.get("verify_command"),
        worker_cmd=config.get("worker_cmd", "auto"),
        worker_timeout=config.get("worker_timeout_seconds", 120),
        mode=config.get("mode", "auto"),
        judge_provider=config.get("provider", "anthropic"),
        judge_model=config.get("model"),
    )
    _print_run_table(result, taskbox, plan.run_id)
```

- [ ] **Step 4: Run all new tests**

```bash
pytest tests/test_taskbox.py -k "reset_failed" -v
pytest tests/test_cli.py -k "rerun" -v
```

Expected: all pass

- [ ] **Step 5: Run full suite**

```bash
pytest tests/ -v
```

Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add aide/taskbox.py aide/cli.py tests/test_taskbox.py tests/test_cli.py
git commit -m "feat: aide rerun --run-id; reset failed tasks and retry with existing plan"
```

---

## Self-Review

**Spec coverage:**

| Improvement | Task |
|---|---|
| asyncio.Queue replaces poll | Task 1 |
| SQLite WAL mode | Task 1 |
| Async CLI + asyncio.to_thread | Task 2 |
| Rich spinner during planning | Task 2 |
| Rich output table | Task 2 (_print_run_table) |
| Live stdout streaming | Task 3 (progress_callback) |
| Per-task completion callback | Task 4 (on_task_complete tests) |
| aide rerun command | Task 5 |

**Placeholder scan:** No TBD, no TODO. All steps have complete code.

**Type consistency:**
- `progress_callback: Callable[[str, str], None]` — defined in Task 3, used in Task 1's manager (_progress_cb)
- `on_task_complete: Callable[[str, str, str], None]` — defined in Task 1's manager signature, tested in Task 4
- `reset_failed_tasks(run_id: str) -> int` — defined in Task 5 Step 2, called in Task 5 Step 3
- `_print_run_table(result, taskbox, run_id)` — defined in Task 2 Step 3, called in Task 5 Step 3

**Dependency order check:**
- Task 1 adds `on_task_complete` and `stream_output` to run_manager ✓
- Task 2 uses `on_task_complete` when calling run_manager ✓ (depends on Task 1)
- Task 3 adds `progress_callback` to run_worker; Task 1 uses it in `_progress_cb` ✓
- Task 5's `_rerun_async` uses `_print_run_table` from Task 2 ✓

**Note for implementer:** Tasks 1 and 2 must be done in order. Tasks 3, 4, 5 are independent of each other but depend on Task 1 being complete.
