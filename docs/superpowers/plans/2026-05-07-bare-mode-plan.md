# Bare Mode (Git-Optional) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make git optional in AIDE by introducing a `Workspace` protocol with `GitWorkspace` and `BareWorkspace` implementations, allowing AIDE to run any agentic task — not just code in a git repo.

**Architecture:** `workspace.py` gains a `Workspace` protocol, `GitWorkspace` (wraps current git worktree logic), `BareWorkspace` (temp dirs, no git), and `workspace_factory()`. The manager uses `workspace_factory` instead of calling git functions directly. Workers pick a TASK.md template based on mode. The CLI gains `--output`, auto-init, and a mode prompt.

**Tech Stack:** Python 3.11+, pathlib, subprocess, shutil, uuid, existing aide codebase.

---

## File Map

| Action | Path |
|--------|------|
| Modify | `aide/workspace.py` |
| Modify | `aide/worker.py` |
| Modify | `aide/manager.py` |
| Modify | `aide/cli.py` |
| Modify | `tests/test_workspace.py` |
| Modify | `tests/test_worker.py` |
| Modify | `tests/test_manager.py` |
| Modify | `tests/test_cli.py` |

---

## Task 1: Workspace protocol, GitWorkspace, BareWorkspace, workspace_factory

**Files:**
- Modify: `aide/workspace.py`
- Modify: `tests/test_workspace.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_workspace.py`:

```python
import shutil
from aide.workspace import (
    BareWorkspace,
    GitWorkspace,
    workspace_factory,
)


# ── BareWorkspace ─────────────────────────────────────────────────────────────

def test_bare_workspace_create_slot_makes_dir(tmp_path):
    ws = BareWorkspace(tmp_path)
    slot_path, slot_id = ws.create_slot("run1", "agent-abc")
    assert slot_path.exists()
    assert slot_path == tmp_path / "run1" / "agent-abc"
    assert len(slot_id) == 8


def test_bare_workspace_integrate_no_verify_succeeds(tmp_path):
    ws = BareWorkspace(tmp_path)
    slot_path, slot_id = ws.create_slot("run1", "agent-abc")
    ok, msg = ws.integrate(slot_path, slot_id, verify_cmd=None)
    assert ok is True
    assert str(slot_path) in msg


def test_bare_workspace_integrate_verify_passes(tmp_path):
    ws = BareWorkspace(tmp_path)
    slot_path, slot_id = ws.create_slot("run1", "agent-abc")
    ok, msg = ws.integrate(slot_path, slot_id, verify_cmd="true")
    assert ok is True


def test_bare_workspace_integrate_verify_fails(tmp_path):
    ws = BareWorkspace(tmp_path)
    slot_path, slot_id = ws.create_slot("run1", "agent-abc")
    ok, msg = ws.integrate(slot_path, slot_id, verify_cmd="false")
    assert ok is False
    assert "verify failed" in msg


def test_bare_workspace_cleanup_slot_is_noop(tmp_path):
    ws = BareWorkspace(tmp_path)
    slot_path, slot_id = ws.create_slot("run1", "agent-abc")
    ws.cleanup_slot(slot_path, slot_id)
    assert slot_path.exists()


def test_bare_workspace_list_slots(tmp_path):
    ws = BareWorkspace(tmp_path)
    ws.create_slot("run1", "agent-abc")
    ws.create_slot("run1", "agent-def")
    slots = ws.list_slots()
    assert len(slots) >= 1
    assert all("path" in s for s in slots)


def test_bare_workspace_mode_attribute(tmp_path):
    ws = BareWorkspace(tmp_path)
    assert ws.mode == "bare"


def test_git_workspace_mode_attribute(git_repo):
    ws = GitWorkspace(git_repo)
    assert ws.mode == "git"


# ── workspace_factory ─────────────────────────────────────────────────────────

def test_workspace_factory_returns_git_workspace(git_repo):
    ws = workspace_factory({"mode": "git"}, git_repo)
    assert isinstance(ws, GitWorkspace)


def test_workspace_factory_returns_bare_workspace(tmp_path):
    ws = workspace_factory({"mode": "bare"}, tmp_path)
    assert isinstance(ws, BareWorkspace)


def test_workspace_factory_auto_detects_git(git_repo):
    ws = workspace_factory({"mode": "auto"}, git_repo)
    assert isinstance(ws, GitWorkspace)


def test_workspace_factory_auto_detects_no_git(tmp_path):
    ws = workspace_factory({"mode": "auto"}, tmp_path)
    assert isinstance(ws, BareWorkspace)


def test_workspace_factory_git_mode_raises_outside_repo(tmp_path):
    with pytest.raises(ValueError, match="Not a git repository"):
        workspace_factory({"mode": "git"}, tmp_path)


def test_init_aide_config_has_mode_field(tmp_path):
    init_aide(tmp_path)
    config = get_config(tmp_path)
    assert config["mode"] == "auto"
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
cd /home/carl/GitHub/galaxy && python -m pytest tests/test_workspace.py::test_bare_workspace_create_slot_makes_dir tests/test_workspace.py::test_workspace_factory_returns_git_workspace -v
```

Expected: `ImportError: cannot import name 'BareWorkspace' from 'aide.workspace'`

- [ ] **Step 3: Rewrite `aide/workspace.py`**

Replace the entire file with:

```python
import json
import shutil
import subprocess
import uuid
from pathlib import Path

_AIDE_DIR = ".aide"


# ── Workspace protocol ────────────────────────────────────────────────────────

class GitWorkspace:
    mode = "git"

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path

    def create_slot(self, run_id: str, agent_id: str) -> tuple[Path, str]:
        branch = f"aide/{run_id}/{agent_id}"
        worktree_path = self.repo_path / _AIDE_DIR / "worktrees" / agent_id
        subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(worktree_path)],
            cwd=self.repo_path, check=True, capture_output=True,
        )
        symlink_env_files(worktree_path, self.repo_path)
        return worktree_path, branch

    def integrate(self, working_path: Path, slot_id: str, verify_cmd: str | None) -> tuple[bool, str]:
        from .integration import run_verify, merge_branch
        passed, verify_output = run_verify(working_path, verify_cmd)
        if not passed:
            return False, f"verify failed:\n{verify_output}"
        merged, merge_output = merge_branch(self.repo_path, slot_id)
        if not merged:
            return False, f"merge failed:\n{merge_output}"
        return True, f"integrated {slot_id}\n{verify_output}\n{merge_output}"

    def cleanup_slot(self, working_path: Path, slot_id: str) -> None:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(working_path)],
            cwd=self.repo_path, check=True, capture_output=True,
        )

    def list_slots(self) -> list[dict]:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=self.repo_path, check=True, capture_output=True, text=True,
        )
        worktrees: list[dict] = []
        current: dict = {}
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                if current:
                    worktrees.append(current)
                current = {"path": line.split(" ", 1)[1]}
            elif line.startswith("branch "):
                current["branch"] = line.split(" ", 1)[1]
            elif line.startswith("HEAD "):
                current["HEAD"] = line.split(" ", 1)[1]
        if current:
            worktrees.append(current)
        return worktrees


class BareWorkspace:
    mode = "bare"

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    def create_slot(self, run_id: str, agent_id: str) -> tuple[Path, str]:
        slot_id = str(uuid.uuid4())[:8]
        slot_path = self.base_dir / run_id / agent_id
        slot_path.mkdir(parents=True, exist_ok=True)
        return slot_path, slot_id

    def integrate(self, working_path: Path, slot_id: str, verify_cmd: str | None) -> tuple[bool, str]:
        if verify_cmd:
            from .integration import run_verify
            passed, output = run_verify(working_path, verify_cmd)
            if not passed:
                return False, f"verify failed:\n{output}"
        return True, f"output at {working_path}"

    def cleanup_slot(self, working_path: Path, slot_id: str) -> None:
        pass  # aide clean handles explicit deletion via shutil.rmtree

    def list_slots(self) -> list[dict]:
        if not self.base_dir.exists():
            return []
        return [
            {"path": str(p), "slot_id": p.name}
            for p in self.base_dir.iterdir()
            if p.is_dir()
        ]


# ── Factory ───────────────────────────────────────────────────────────────────

def _is_git_repo(path: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=path, capture_output=True,
    )
    return result.returncode == 0


def workspace_factory(
    config: dict,
    repo_path: Path,
    output_dir: Path | None = None,
) -> GitWorkspace | BareWorkspace:
    mode = config.get("mode", "auto")
    if mode == "auto":
        mode = "git" if _is_git_repo(repo_path) else "bare"
    if mode == "git":
        if not _is_git_repo(repo_path):
            raise ValueError("Not a git repository. Use mode: bare or auto.")
        return GitWorkspace(repo_path)
    base = output_dir or (repo_path / _AIDE_DIR / "runs")
    return BareWorkspace(base)


# ── Module-level helpers (preserved for backwards compatibility) ──────────────

def is_initialized(repo_path: Path) -> bool:
    return (repo_path / _AIDE_DIR).exists()


def init_aide(repo_path: Path) -> Path:
    aide_dir = repo_path / _AIDE_DIR
    (aide_dir / "worktrees").mkdir(parents=True, exist_ok=True)
    (aide_dir / "runs").mkdir(parents=True, exist_ok=True)
    config_path = aide_dir / "config.json"
    if not config_path.exists():
        config_path.write_text(
            json.dumps(
                {
                    "mode": "auto",
                    "provider": "anthropic",
                    "model": "claude-opus-4-7",
                    "auth_mode": "auto",
                    "api_key_env": "ANTHROPIC_API_KEY",
                    "worker_cmd": "auto",
                    "verify_command": None,
                    "default_agent_count": None,
                    "worker_timeout_seconds": 120,
                    "max_concurrent_workers": 20,
                },
                indent=2,
            )
        )
    return aide_dir


def get_config(repo_path: Path) -> dict:
    config_path = repo_path / _AIDE_DIR / "config.json"
    if config_path.exists():
        return json.loads(config_path.read_text())
    return {}


def create_worktree(repo_path: Path, run_id: str, agent_id: str) -> tuple[Path, str]:
    branch = f"aide/{run_id}/{agent_id}"
    worktree_path = repo_path / _AIDE_DIR / "worktrees" / agent_id
    subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(worktree_path)],
        cwd=repo_path, check=True, capture_output=True,
    )
    return worktree_path, branch


def delete_worktree(repo_path: Path, worktree_path: Path) -> None:
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_path)],
        cwd=repo_path, check=True, capture_output=True,
    )


def list_worktrees(repo_path: Path) -> list[dict]:
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo_path, check=True, capture_output=True, text=True,
    )
    worktrees: list[dict] = []
    current: dict = {}
    for line in result.stdout.splitlines():
        if line.startswith("worktree "):
            if current:
                worktrees.append(current)
            current = {"path": line.split(" ", 1)[1]}
        elif line.startswith("branch "):
            current["branch"] = line.split(" ", 1)[1]
        elif line.startswith("HEAD "):
            current["HEAD"] = line.split(" ", 1)[1]
    if current:
        worktrees.append(current)
    return worktrees


def symlink_env_files(worktree_path: Path, repo_path: Path) -> list[Path]:
    candidates = [".env", ".env.local", "node_modules", "venv", ".venv", "__pycache__"]
    linked: list[Path] = []
    for name in candidates:
        src = repo_path / name
        dst = worktree_path / name
        if src.exists() and not dst.exists():
            dst.symlink_to(src)
            linked.append(dst)
    return linked


def detect_verify_command(repo_path: Path) -> str | None:
    if (repo_path / "pyproject.toml").exists() and (repo_path / "tests").exists():
        return "pytest"
    if (repo_path / "package.json").exists():
        return "npm test"
    if (repo_path / "Makefile").exists():
        return "make test"
    return None
```

- [ ] **Step 4: Run all workspace tests**

```bash
cd /home/carl/GitHub/galaxy && python -m pytest tests/test_workspace.py -v
```

Expected: all pass (including the new bare workspace + factory tests and existing tests).

- [ ] **Step 5: Commit**

```bash
cd /home/carl/GitHub/galaxy && git add aide/workspace.py tests/test_workspace.py && git commit -m "feat: Workspace protocol — GitWorkspace, BareWorkspace, workspace_factory"
```

---

## Task 2: Worker bare mode template

**Files:**
- Modify: `aide/worker.py`
- Modify: `tests/test_worker.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_worker.py`:

```python
@pytest.mark.asyncio
async def test_worker_bare_mode_writes_bare_template(db, tmp_path):
    make_agent(db, tmp_path)
    await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Generate three business names for a coffee shop",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, worker_cmd="true",
        mode="bare",
    )
    content = (tmp_path / "TASK.md").read_text()
    assert "OUTPUT.md" in content
    assert "git commit" not in content


@pytest.mark.asyncio
async def test_worker_git_mode_writes_git_template(db, tmp_path):
    make_agent(db, tmp_path)
    await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Add input validation",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, worker_cmd="true",
        mode="git",
    )
    content = (tmp_path / "TASK.md").read_text()
    assert "git commit" in content
    assert "OUTPUT.md" not in content
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
cd /home/carl/GitHub/galaxy && python -m pytest tests/test_worker.py::test_worker_bare_mode_writes_bare_template -v
```

Expected: FAIL — `run_worker() got an unexpected keyword argument 'mode'`

- [ ] **Step 3: Update `aide/worker.py`**

Replace the file with:

```python
import asyncio
import uuid
from datetime import datetime
from pathlib import Path

from .models import Message
from .taskbox import Taskbox
from .providers import detect_worker_cmd

_GIT_TASK_TEMPLATE = """\
# Agent Task

{description}

## Instructions
- Work only within this directory
- Run tests to verify your work
- Commit when done: git add -A && git commit -m "feat: {short_desc}"
- Do NOT push

## Context
- Run ID: {run_id}
- Agent ID: {agent_id}
"""

_BARE_TASK_TEMPLATE = """\
# Agent Task

{description}

## Instructions
- Work only within this directory
- Write any file output to this directory
- If the task produces text (names, copy, analysis), write it to OUTPUT.md
- Do NOT use git

## Context
- Run ID: {run_id}
- Agent ID: {agent_id}
"""


async def run_worker(
    agent_id: str,
    run_id: str,
    task_id: str,
    task_description: str,
    worktree_path: Path,
    taskbox: Taskbox,
    timeout: int = 120,
    worker_cmd: str = "auto",
    mode: str = "git",
) -> None:
    cmd = worker_cmd if worker_cmd != "auto" else detect_worker_cmd()
    if cmd is None:
        taskbox.send_message(
            Message(
                id=str(uuid.uuid4()),
                type="ERROR",
                from_agent=agent_id,
                to_agent="manager",
                payload={
                    "task_id": task_id,
                    "error": "No worker CLI found. Install claude, codex, or gemini.",
                },
                created_at=datetime.utcnow(),
            )
        )
        taskbox.update_agent_status(agent_id, "failed")
        return

    short_desc = task_description[:50].replace("\n", " ")
    template = _BARE_TASK_TEMPLATE if mode == "bare" else _GIT_TASK_TEMPLATE
    (worktree_path / "TASK.md").write_text(
        template.format(
            description=task_description,
            run_id=run_id,
            agent_id=agent_id,
            short_desc=short_desc,
        )
    )

    taskbox.update_agent_status(agent_id, "working")

    try:
        proc = await asyncio.create_subprocess_exec(
            cmd,
            "--print",
            "Please complete the task described in TASK.md",
            cwd=worktree_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        taskbox.update_agent_status(agent_id, "working", pid=proc.pid)

        async def _drain_stdout() -> None:
            assert proc.stdout
            async for line in proc.stdout:
                taskbox.send_message(
                    Message(
                        id=str(uuid.uuid4()),
                        type="PROGRESS",
                        from_agent=agent_id,
                        to_agent="manager",
                        payload={"line": line.decode().rstrip()},
                        created_at=datetime.utcnow(),
                    )
                )

        try:
            await asyncio.wait_for(
                asyncio.gather(proc.wait(), _drain_stdout()),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            taskbox.send_message(
                Message(
                    id=str(uuid.uuid4()),
                    type="ERROR",
                    from_agent=agent_id,
                    to_agent="manager",
                    payload={"task_id": task_id, "error": "timeout"},
                    created_at=datetime.utcnow(),
                )
            )
            taskbox.update_agent_status(agent_id, "failed")
            return

        if proc.returncode == 0:
            taskbox.send_message(
                Message(
                    id=str(uuid.uuid4()),
                    type="COMPLETE",
                    from_agent=agent_id,
                    to_agent="manager",
                    payload={"task_id": task_id},
                    created_at=datetime.utcnow(),
                )
            )
            taskbox.update_agent_status(agent_id, "done")
        else:
            stderr = b""
            if proc.stderr:
                stderr = await proc.stderr.read()
            taskbox.send_message(
                Message(
                    id=str(uuid.uuid4()),
                    type="ERROR",
                    from_agent=agent_id,
                    to_agent="manager",
                    payload={
                        "task_id": task_id,
                        "returncode": proc.returncode,
                        "stderr": stderr.decode(),
                    },
                    created_at=datetime.utcnow(),
                )
            )
            taskbox.update_agent_status(agent_id, "failed")

    except Exception as exc:
        taskbox.send_message(
            Message(
                id=str(uuid.uuid4()),
                type="ERROR",
                from_agent=agent_id,
                to_agent="manager",
                payload={"task_id": task_id, "error": str(exc)},
                created_at=datetime.utcnow(),
            )
        )
        taskbox.update_agent_status(agent_id, "failed")
```

- [ ] **Step 4: Run all worker tests**

```bash
cd /home/carl/GitHub/galaxy && python -m pytest tests/test_worker.py -v --ignore-glob="*timeout*" -k "not timeout"
```

Expected: all pass except the slow timeout test.

- [ ] **Step 5: Commit**

```bash
cd /home/carl/GitHub/galaxy && git add aide/worker.py tests/test_worker.py && git commit -m "feat: worker mode param — git template with commit, bare template with OUTPUT.md"
```

---

## Task 3: Manager uses workspace_factory

**Files:**
- Modify: `aide/manager.py`
- Modify: `tests/test_manager.py`

- [ ] **Step 1: Write failing test for bare mode**

Add to `tests/test_manager.py` (append after existing tests):

```python
@pytest.mark.asyncio
async def test_manager_bare_mode_returns_output_paths(db, tmp_path):
    """run_manager with mode=bare includes output_paths in result."""
    plan = _make_plan()

    slot_path = tmp_path / "runs" / "testrun1" / "agent-abc"
    slot_path.mkdir(parents=True, exist_ok=True)

    mock_workspace = MagicMock()
    mock_workspace.mode = "bare"
    mock_workspace.create_slot.return_value = (slot_path, "slot-abc1")
    mock_workspace.integrate.return_value = (True, f"output at {slot_path}")
    mock_workspace.cleanup_slot.return_value = None

    with patch("aide.manager.workspace_factory", return_value=mock_workspace), \
         patch("aide.manager.run_worker", new_callable=AsyncMock,
               side_effect=_make_fake_worker(db)):
        result = await run_manager(plan, tmp_path, db, mode="bare")

    assert result["status"] == "complete"
    assert result["completed"] == 1
    assert "output_paths" in result
    assert str(slot_path) in result["output_paths"]
```

- [ ] **Step 2: Run new test to verify it fails**

```bash
cd /home/carl/GitHub/galaxy && python -m pytest tests/test_manager.py::test_manager_bare_mode_returns_output_paths -v
```

Expected: FAIL — `run_manager() got an unexpected keyword argument 'mode'`

- [ ] **Step 3: Rewrite `aide/manager.py`**

Replace the entire file with:

```python
import asyncio
import uuid
from datetime import datetime
from pathlib import Path

from .models import AgentRecord, Plan, RunRecord
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
    completed: set[str] = set()
    failed: set[str] = set()
    in_flight: dict[str, asyncio.Task] = {}
    task_to_agent: dict[str, str] = {}
    output_paths: list[str] = []
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _dispatch(subtask) -> None:
        agent_id = f"agent-{str(uuid.uuid4())[:6]}"
        slot_path, slot_id = workspace.create_slot(plan.run_id, agent_id)

        taskbox.save_agent(
            AgentRecord(
                id=agent_id, run_id=plan.run_id,
                worktree_path=str(slot_path), branch=slot_id,
                task_id=subtask.id, last_heartbeat=datetime.utcnow(),
            )
        )
        taskbox.update_task_status(
            subtask.id, "in_progress",
            assigned_agent=agent_id,
            worktree_path=str(slot_path),
            branch=slot_id,
        )
        task_to_agent[subtask.id] = agent_id

        async with semaphore:
            await run_worker(
                agent_id=agent_id, run_id=plan.run_id,
                task_id=subtask.id, task_description=subtask.description,
                worktree_path=slot_path, taskbox=taskbox,
                timeout=worker_timeout, worker_cmd=worker_cmd,
                mode=worker_mode,
            )

    while len(completed) + len(failed) < len(all_ids):
        dispatchable = [
            t for t in plan.tasks
            if t.id not in completed
            and t.id not in failed
            and t.id not in task_to_agent
            and all(dep in completed for dep in t.depends_on)
        ]
        for subtask in dispatchable:
            in_flight[subtask.id] = asyncio.create_task(_dispatch(subtask))

        for msg in taskbox.get_unprocessed_messages("manager"):
            taskbox.mark_message_processed(msg.id)
            task_id = msg.payload.get("task_id")
            if not task_id:
                continue

            if msg.type == "COMPLETE":
                agent_id = task_to_agent.get(task_id)
                agents = taskbox.get_agents(plan.run_id)
                agent_rec = next((a for a in agents if a.id == agent_id), None)
                if agent_rec:
                    ok, out = workspace.integrate(
                        Path(agent_rec.worktree_path), agent_rec.branch, verify_cmd,
                    )
                    if ok:
                        completed.add(task_id)
                        taskbox.update_task_status(task_id, "complete")
                        if worker_mode == "bare":
                            output_paths.append(agent_rec.worktree_path)
                    else:
                        failed.add(task_id)
                        taskbox.update_task_status(task_id, "failed")
                else:
                    failed.add(task_id)
                    taskbox.update_task_status(task_id, "failed")
                in_flight.pop(task_id, None)

            elif msg.type == "ERROR":
                if task_id:
                    failed.add(task_id)
                    taskbox.update_task_status(task_id, "failed")
                    in_flight.pop(task_id, None)

        for task in plan.tasks:
            if (
                task.id not in completed
                and task.id not in failed
                and task.id not in task_to_agent
                and any(dep in failed for dep in task.depends_on)
            ):
                failed.add(task.id)
                taskbox.update_task_status(task.id, "failed")

        remaining = all_ids - completed - failed
        if not remaining:
            break

        newly_dispatchable = any(
            t.id not in completed
            and t.id not in failed
            and t.id not in task_to_agent
            and all(dep in completed for dep in t.depends_on)
            for t in plan.tasks
        )
        if in_flight or newly_dispatchable:
            await asyncio.sleep(0.05)
        else:
            break

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

- [ ] **Step 4: Update existing tests in `tests/test_manager.py`**

The existing tests patch `aide.manager.integrate_worktree`, `aide.manager.create_worktree`, and `aide.manager.symlink_env_files`. These imports no longer exist in manager.py. Update the file to use `workspace_factory` mocking.

Replace the entire `tests/test_manager.py` with:

```python
import asyncio
import uuid
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from aide.manager import run_manager
from aide.models import Message, Plan, SubTask
from aide.workspace import init_aide


def _make_plan(tasks=None, run_id="testrun1"):
    if tasks is None:
        tasks = [SubTask(id="t1", description="Do thing A", depends_on=[])]
    return Plan(
        run_id=run_id,
        original_prompt="do stuff",
        agent_count=len(tasks),
        complexity_score=10,
        tasks=tasks,
    )


def _make_fake_worker(db):
    async def _worker(**kwargs):
        db.send_message(Message(
            id=str(uuid.uuid4()), type="COMPLETE",
            from_agent=kwargs["agent_id"], to_agent="manager",
            payload={"task_id": kwargs["task_id"]},
            created_at=datetime.utcnow(),
        ))
        db.update_agent_status(kwargs["agent_id"], "done")
    return _worker


def _make_mock_workspace(tmp_path, integrate_result=(True, "ok"), mode="git"):
    mock_ws = MagicMock()
    mock_ws.mode = mode
    call_count = [0]

    def _create_slot(run_id, agent_id):
        p = tmp_path / f".aide/worktrees/{agent_id}"
        p.mkdir(parents=True, exist_ok=True)
        return p, f"aide/{run_id}/{agent_id}"

    mock_ws.create_slot.side_effect = _create_slot
    mock_ws.integrate.return_value = integrate_result
    mock_ws.cleanup_slot.return_value = None
    return mock_ws


@pytest.mark.asyncio
async def test_manager_single_task_success(db, git_repo):
    init_aide(git_repo)
    plan = _make_plan()
    mock_ws = _make_mock_workspace(git_repo)

    with patch("aide.manager.workspace_factory", return_value=mock_ws), \
         patch("aide.manager.run_worker", new_callable=AsyncMock,
               side_effect=_make_fake_worker(db)):
        result = await run_manager(plan, git_repo, db, verify_cmd="true")

    assert result["status"] == "complete"
    assert result["completed"] == 1
    assert result["failed"] == 0


@pytest.mark.asyncio
async def test_manager_task_dependency_order(db, git_repo):
    init_aide(git_repo)
    tasks = [
        SubTask(id="t1", description="First", depends_on=[]),
        SubTask(id="t2", description="Second", depends_on=["t1"]),
    ]
    plan = _make_plan(tasks, run_id="deptest")
    dispatch_order = []
    mock_ws = _make_mock_workspace(git_repo)

    async def _ordered_worker(**kwargs):
        dispatch_order.append(kwargs["task_id"])
        db.send_message(Message(
            id=str(uuid.uuid4()), type="COMPLETE",
            from_agent=kwargs["agent_id"], to_agent="manager",
            payload={"task_id": kwargs["task_id"]},
            created_at=datetime.utcnow(),
        ))
        db.update_agent_status(kwargs["agent_id"], "done")

    with patch("aide.manager.workspace_factory", return_value=mock_ws), \
         patch("aide.manager.run_worker", new_callable=AsyncMock,
               side_effect=_ordered_worker):
        result = await run_manager(plan, git_repo, db, verify_cmd="true")

    assert result["status"] == "complete"
    assert result["completed"] == 2
    assert dispatch_order.index("t1") < dispatch_order.index("t2")


@pytest.mark.asyncio
async def test_manager_failed_integration_marks_task_failed(db, git_repo):
    init_aide(git_repo)
    plan = _make_plan()
    mock_ws = _make_mock_workspace(git_repo, integrate_result=(False, "tests failed"))

    with patch("aide.manager.workspace_factory", return_value=mock_ws), \
         patch("aide.manager.run_worker", new_callable=AsyncMock,
               side_effect=_make_fake_worker(db)):
        result = await run_manager(plan, git_repo, db, verify_cmd="true")

    assert result["status"] == "failed"
    assert result["failed"] == 1


@pytest.mark.asyncio
async def test_manager_run_saved_to_taskbox(db, git_repo):
    init_aide(git_repo)
    plan = _make_plan()
    mock_ws = _make_mock_workspace(git_repo)

    with patch("aide.manager.workspace_factory", return_value=mock_ws), \
         patch("aide.manager.run_worker", new_callable=AsyncMock,
               side_effect=_make_fake_worker(db)):
        await run_manager(plan, git_repo, db, verify_cmd="true")

    run_rec = db.get_run(plan.run_id)
    assert run_rec is not None
    assert run_rec.status == "complete"


@pytest.mark.asyncio
async def test_manager_dependent_task_fails_when_dep_fails(db, git_repo):
    init_aide(git_repo)
    tasks = [
        SubTask(id="t1", description="First", depends_on=[]),
        SubTask(id="t2", description="Blocked by t1", depends_on=["t1"]),
    ]
    plan = _make_plan(tasks, run_id="failtest")
    mock_ws = _make_mock_workspace(git_repo, integrate_result=(False, "tests failed"))

    async def _failing_worker(**kwargs):
        db.send_message(Message(
            id=str(uuid.uuid4()), type="COMPLETE",
            from_agent=kwargs["agent_id"], to_agent="manager",
            payload={"task_id": kwargs["task_id"]},
            created_at=datetime.utcnow(),
        ))

    with patch("aide.manager.workspace_factory", return_value=mock_ws), \
         patch("aide.manager.run_worker", new_callable=AsyncMock,
               side_effect=_failing_worker):
        result = await run_manager(plan, git_repo, db, verify_cmd="true")

    assert result["failed"] >= 1


@pytest.mark.asyncio
async def test_manager_bare_mode_returns_output_paths(db, tmp_path):
    """run_manager with mode=bare includes output_paths in result."""
    plan = _make_plan()

    slot_path = tmp_path / "runs" / "testrun1" / "agent-abc"
    slot_path.mkdir(parents=True, exist_ok=True)

    mock_ws = MagicMock()
    mock_ws.mode = "bare"
    mock_ws.create_slot.return_value = (slot_path, "slot-abc1")
    mock_ws.integrate.return_value = (True, f"output at {slot_path}")
    mock_ws.cleanup_slot.return_value = None

    with patch("aide.manager.workspace_factory", return_value=mock_ws), \
         patch("aide.manager.run_worker", new_callable=AsyncMock,
               side_effect=_make_fake_worker(db)):
        result = await run_manager(plan, tmp_path, db, mode="bare")

    assert result["status"] == "complete"
    assert result["completed"] == 1
    assert "output_paths" in result
    assert str(slot_path) in result["output_paths"]
```

- [ ] **Step 5: Run all manager tests**

```bash
cd /home/carl/GitHub/galaxy && python -m pytest tests/test_manager.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 6: Run full suite (excluding slow worker test)**

```bash
cd /home/carl/GitHub/galaxy && python -m pytest --ignore=tests/test_worker.py -v 2>&1 | tail -10
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
cd /home/carl/GitHub/galaxy && git add aide/manager.py tests/test_manager.py && git commit -m "refactor: manager uses workspace_factory — mode-agnostic dispatch and integration"
```

---

## Task 4: CLI — auto-init, --output, mode prompt, bare output paths, clean

**Files:**
- Modify: `aide/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_cli.py`:

```python
def test_run_auto_inits_if_not_initialized(runner, tmp_path, mocker):
    """aide run auto-inits if .aide/ doesn't exist."""
    from aide.models import Plan, SubTask
    fake_plan = Plan(
        run_id="r1", original_prompt="do a thing",
        agent_count=1, complexity_score=5,
        tasks=[SubTask(id="t1", description="do a thing", depends_on=[])],
    )
    mocker.patch("aide.cli.plan_task", return_value=fake_plan)
    mocker.patch("aide.cli.run_manager", new=AsyncMock(return_value={
        "run_id": "r1", "status": "complete", "completed": 1, "failed": 0, "total": 1,
    }))

    result = runner.invoke(main, ["run", "do a thing", "--repo", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert (tmp_path / ".aide").exists()


def test_run_bare_prints_output_paths(runner, git_repo, mocker):
    """aide run prints → path for each output_path in result."""
    init_aide(git_repo)
    from aide.models import Plan, SubTask
    fake_plan = Plan(
        run_id="r1", original_prompt="name my biz",
        agent_count=1, complexity_score=5,
        tasks=[SubTask(id="t1", description="name my biz", depends_on=[])],
    )
    mocker.patch("aide.cli.plan_task", return_value=fake_plan)
    mocker.patch("aide.cli.run_manager", new=AsyncMock(return_value={
        "run_id": "r1", "status": "complete", "completed": 1, "failed": 0, "total": 1,
        "output_paths": ["/tmp/fake/output/agent-abc"],
    }))

    result = runner.invoke(main, ["run", "name my biz", "--repo", str(git_repo)])
    assert result.exit_code == 0, result.output
    assert "/tmp/fake/output/agent-abc" in result.output


def test_init_no_interactive_writes_mode_auto(runner, git_repo):
    """aide init --no-interactive writes mode: auto to config."""
    import json
    result = runner.invoke(main, ["init", str(git_repo), "--no-interactive"])
    assert result.exit_code == 0
    config = json.loads((git_repo / ".aide" / "config.json").read_text())
    assert config["mode"] == "auto"


def test_clean_bare_mode_removes_slot_dirs(runner, tmp_path, mocker):
    """aide clean in bare mode calls shutil.rmtree on slot dirs."""
    init_aide(tmp_path)
    import json
    config_path = tmp_path / ".aide" / "config.json"
    config = json.loads(config_path.read_text())
    config["mode"] = "bare"
    config_path.write_text(json.dumps(config))

    from aide.workspace import BareWorkspace
    mock_ws = MagicMock(spec=BareWorkspace)
    mock_ws.mode = "bare"
    mock_ws.list_slots.return_value = [
        {"path": str(tmp_path / "slot1"), "slot_id": "slot1"},
        {"path": str(tmp_path / "slot2"), "slot_id": "slot2"},
    ]
    mocker.patch("aide.cli.workspace_factory", return_value=mock_ws)
    mock_rmtree = mocker.patch("aide.cli.shutil.rmtree")

    result = runner.invoke(main, ["clean", "--repo", str(tmp_path)])
    assert result.exit_code == 0
    assert mock_rmtree.call_count == 2
    assert "Removed 2" in result.output
```

- [ ] **Step 2: Run new tests to verify they fail**

```bash
cd /home/carl/GitHub/galaxy && python -m pytest tests/test_cli.py::test_run_auto_inits_if_not_initialized tests/test_cli.py::test_run_bare_prints_output_paths -v
```

Expected: `test_run_auto_inits_if_not_initialized` FAIL (run exits 1 when not initialized), `test_run_bare_prints_output_paths` FAIL (no path in output).

- [ ] **Step 3: Rewrite `aide/cli.py`**

Replace entire file with:

```python
import asyncio
import json
import shutil
from pathlib import Path

import click

from .manager import run_manager
from .planner import plan_task
from .providers import SUPPORTED_PROVIDERS, detect_worker_cmd
from .taskbox import Taskbox
from .workspace import (
    BareWorkspace,
    get_config,
    init_aide,
    is_initialized,
    workspace_factory,
)


@click.group()
def main():
    pass


@main.command()
@click.argument("repo_path", default=".", type=click.Path())
@click.option("--no-interactive", is_flag=True, default=False,
              help="Skip prompts and use defaults.")
def init(repo_path, no_interactive):
    """Initialize AIDE in a directory (git repo not required)."""
    path = Path(repo_path).resolve()
    if is_initialized(path):
        click.echo(f"AIDE already initialized at {path}")
        return

    if no_interactive:
        init_aide(path)
        click.echo(f"AIDE initialized at {path}")
        return

    # Interactive setup
    provider = click.prompt(
        "Provider",
        type=click.Choice(list(SUPPORTED_PROVIDERS.keys())),
        default="anthropic",
    )
    meta = SUPPORTED_PROVIDERS[provider]
    model = click.prompt("Model", default=meta["default_model"])
    auth_choices = (
        ["auto", "api_key", "subscription"]
        if meta["supports_subscription"]
        else ["auto", "api_key"]
    )
    auth_mode = click.prompt(
        "Auth mode",
        type=click.Choice(auth_choices),
        default="auto",
    )
    api_key_env = click.prompt("API key env var", default=meta["api_key_env"])
    mode = click.prompt(
        "Workspace mode",
        type=click.Choice(["auto", "git", "bare"]),
        default="auto",
    )

    detected_cli = detect_worker_cmd()
    if detected_cli:
        click.echo(f"Detected worker CLI: {detected_cli} ✓")
    else:
        click.echo("Warning: No worker CLI found (claude/codex/gemini). Install one before running.")

    init_aide(path)

    config_path = path / ".aide" / "config.json"
    existing = json.loads(config_path.read_text())
    existing.update({
        "mode": mode,
        "provider": provider,
        "model": model,
        "auth_mode": auth_mode,
        "api_key_env": api_key_env,
    })
    config_path.write_text(json.dumps(existing, indent=2))

    click.echo(f"AIDE initialized at {path}")


@main.command()
@click.argument("prompt", required=False)
@click.option("--file", "-f", "task_file", type=click.Path(exists=True))
@click.option("--repo", default=".", type=click.Path())
@click.option("--agents", type=int, default=None)
@click.option("--verify", "verify_cmd", default=None)
@click.option("--output", "output_dir", default=None, type=click.Path(),
              help="Output directory for bare mode agent results.")
def run(prompt, task_file, repo, agents, verify_cmd, output_dir):
    """Run agents on a task prompt or .md file."""
    if prompt and task_file:
        click.echo("Error: provide either a prompt or --file, not both.")
        raise SystemExit(1)
    if not prompt and not task_file:
        click.echo("Error: provide a prompt or --file.", err=True)
        raise SystemExit(1)

    repo_path = Path(repo).resolve()

    if not is_initialized(repo_path):
        init_aide(repo_path)

    if task_file:
        prompt = Path(task_file).read_text()

    config = get_config(repo_path)

    plan = plan_task(
        prompt,
        provider=config.get("provider", "anthropic"),
        model=config.get("model"),
        auth_mode=config.get("auth_mode", "auto"),
        api_key_env=config.get("api_key_env"),
        agent_count_override=agents,
    )

    taskbox = Taskbox(repo_path / ".aide" / "aide.db")

    result = asyncio.run(
        run_manager(
            plan,
            repo_path,
            taskbox,
            max_concurrent=config.get("max_concurrent_workers", 20),
            verify_cmd=verify_cmd or config.get("verify_command"),
            worker_cmd=config.get("worker_cmd", "auto"),
            worker_timeout=config.get("worker_timeout_seconds", 120),
            mode=config.get("mode", "auto"),
            output_dir=Path(output_dir) if output_dir else None,
        )
    )

    click.echo(
        f"Run {result['run_id']}: {result['status']} "
        f"({result['completed']}/{result['total']} tasks)"
    )
    for path in result.get("output_paths", []):
        click.echo(f"  → {path}")


@main.command()
@click.option("--repo", default=".", type=click.Path())
@click.option("--run-id", default=None)
def status(repo, run_id):
    """Show status of runs."""
    repo_path = Path(repo).resolve()
    taskbox = Taskbox(repo_path / ".aide" / "aide.db")

    if run_id:
        run_rec = taskbox.get_run(run_id)
        if not run_rec:
            click.echo(f"Run {run_id} not found.")
            return
        completed_at = run_rec.completed_at.isoformat() if run_rec.completed_at else "running"
        click.echo(f"{run_rec.id}: {run_rec.status} ({completed_at})")
        tasks = taskbox.get_tasks(run_id)
        for task in tasks:
            click.echo(f"  {task.id}: {task.status} — {task.description}")
    else:
        runs = taskbox.list_runs()
        if not runs:
            click.echo("No runs found.")
            return
        for run_rec in runs[:5]:
            completed_at = run_rec.completed_at.isoformat() if run_rec.completed_at else "running"
            click.echo(f"{run_rec.id}: {run_rec.status} ({completed_at})")


@main.command()
@click.option("--repo", default=".", type=click.Path())
@click.option("--all", "all_slots", is_flag=True, default=False)
def clean(repo, all_slots):
    """Remove finished agent workspaces."""
    repo_path = Path(repo).resolve()
    config = get_config(repo_path) if is_initialized(repo_path) else {}
    ws = workspace_factory(config, repo_path)
    slots = ws.list_slots()
    count = 0
    for slot in slots:
        slot_path = Path(slot["path"])
        if isinstance(ws, BareWorkspace):
            shutil.rmtree(slot_path, ignore_errors=True)
        else:
            ws.cleanup_slot(slot_path, slot.get("branch", slot.get("slot_id", "")))
        count += 1
    click.echo(f"Removed {count} worktrees.")
```

- [ ] **Step 4: Update the existing `test_clean_removes_worktrees` test**

The old test patches `aide.cli.list_worktrees` and `aide.cli.delete_worktree`. The new `clean` command uses `workspace_factory`. Update the test:

Find and replace `test_clean_removes_worktrees` in `tests/test_cli.py`:

```python
def test_clean_removes_worktrees(runner, git_repo, mocker):
    """aide clean calls cleanup_slot for each listed slot (git mode)."""
    init_aide(git_repo)

    from aide.workspace import GitWorkspace
    mock_ws = MagicMock(spec=GitWorkspace)
    mock_ws.mode = "git"
    mock_ws.list_slots.return_value = [
        {"path": "/tmp/wt1", "branch": "aide/r1/agent-1"},
        {"path": "/tmp/wt2", "branch": "aide/r1/agent-2"},
    ]
    mocker.patch("aide.cli.workspace_factory", return_value=mock_ws)

    result = runner.invoke(main, ["clean", "--repo", str(git_repo)])
    assert result.exit_code == 0
    assert mock_ws.cleanup_slot.call_count == 2
    assert "Removed 2 worktrees" in result.output
```

- [ ] **Step 5: Run all CLI tests**

```bash
cd /home/carl/GitHub/galaxy && python -m pytest tests/test_cli.py -v
```

Expected: all pass.

- [ ] **Step 6: Run full test suite**

```bash
cd /home/carl/GitHub/galaxy && python -m pytest --ignore=tests/test_worker.py -v 2>&1 | tail -10
```

Expected: all pass.

- [ ] **Step 7: Verify CLI help**

```bash
cd /home/carl/GitHub/galaxy && aide run --help
```

Expected output includes `--output` option.

- [ ] **Step 8: Commit and push**

```bash
cd /home/carl/GitHub/galaxy && git add aide/cli.py tests/test_cli.py && git commit -m "feat: CLI bare mode — auto-init, --output option, mode prompt, output paths display"
git push origin main
```
