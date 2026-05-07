# Galaxy CAID Orchestrator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `galaxy-caid`, a Python CLI tool that uses CAID (Centralized Async Isolated Delegation) to fan out coding tasks across N Claude Code workers in isolated git worktrees.

**Architecture:** Planner (Anthropic API) decomposes a prompt into a subtask DAG, Manager (asyncio) fans out to Worker subprocesses each running `claude --print` in its own git worktree, and Integration Engine test-gates + merges completed work back to main. SQLite Taskbox handles all inter-component messaging.

**Tech Stack:** Python 3.11+, anthropic SDK, click, asyncio, sqlite3 (stdlib), pytest, pytest-asyncio, pytest-mock

---

## File Map

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package config, entry point, dependencies |
| `galaxy/__init__.py` | Package init |
| `galaxy/models.py` | Dataclasses: SubTask, Plan, Message, AgentRecord, RunRecord |
| `galaxy/taskbox.py` | SQLite message bus — CRUD for tasks/messages/agents/runs |
| `galaxy/workspace.py` | Git worktree lifecycle, .galaxy/ init, env symlinking |
| `galaxy/planner.py` | Anthropic API call → subtask DAG + agent count |
| `galaxy/worker.py` | Async subprocess wrapping `claude --print` in a worktree |
| `galaxy/integration.py` | Run verify command + git merge |
| `galaxy/manager.py` | asyncio orchestrator — fan-out, monitor Taskbox, trigger integration |
| `galaxy/cli.py` | Click CLI: init, run, status, clean |
| `tests/conftest.py` | Shared pytest fixtures (git_repo, db, runner) |
| `tests/test_models.py` | Model construction and defaults |
| `tests/test_taskbox.py` | SQLite CRUD, message lifecycle |
| `tests/test_workspace.py` | Worktree create/delete/list, env symlinking |
| `tests/test_planner.py` | Agent count formula, mock Anthropic API, JSON parsing |
| `tests/test_worker.py` | Subprocess spawning, COMPLETE/ERROR signals, timeout |
| `tests/test_integration.py` | Verify detection, run_verify, merge_branch |
| `tests/test_manager.py` | Fan-out dispatch, dependency ordering, failure handling |
| `tests/test_cli.py` | Click test runner for all CLI commands |
| `README.md` | Install and operation instructions |

---

## Task 1: Project Scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `galaxy/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.backends.legacy:build"

[project]
name = "galaxy-caid"
version = "0.1.0"
description = "CAID multi-agent AI orchestrator using git worktrees"
requires-python = ">=3.11"
dependencies = [
    "anthropic>=0.40.0",
    "click>=8.0",
]

[project.scripts]
galaxy = "galaxy.cli:main"

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-mock>=3.12",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Create package and test directories**

```bash
mkdir -p galaxy tests
touch galaxy/__init__.py tests/__init__.py
```

- [ ] **Step 3: Create `tests/conftest.py`**

```python
import subprocess
import tempfile
import pytest
from pathlib import Path
from click.testing import CliRunner
from galaxy.taskbox import Taskbox


@pytest.fixture
def git_repo():
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
        (repo / "README.md").write_text("test")
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
        yield repo


@pytest.fixture
def db(tmp_path):
    return Taskbox(tmp_path / "test.db")


@pytest.fixture
def runner():
    return CliRunner()
```

- [ ] **Step 4: Install package in dev mode**

```bash
pip install -e ".[dev]"
```

Expected: `Successfully installed galaxy-caid-0.1.0`

- [ ] **Step 5: Verify pytest runs**

```bash
pytest tests/ -v
```

Expected: `no tests ran` (0 collected)

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml galaxy/__init__.py tests/__init__.py tests/conftest.py
git commit -m "feat: project scaffold with pyproject.toml"
```

---

## Task 2: Data Models

**Files:**
- Create: `galaxy/models.py`
- Create: `tests/test_models.py`

- [ ] **Step 1: Write failing tests in `tests/test_models.py`**

```python
from datetime import datetime
import pytest
from galaxy.models import SubTask, Plan, Message, AgentRecord, RunRecord


def test_subtask_defaults():
    t = SubTask(id="t1", description="Do thing", depends_on=[])
    assert t.status == "pending"
    assert t.assigned_agent is None
    assert t.worktree_path is None
    assert t.branch is None


def test_subtask_with_deps():
    t = SubTask(id="t2", description="Do other thing", depends_on=["t1"])
    assert t.depends_on == ["t1"]


def test_plan_creation():
    tasks = [SubTask(id="t1", description="task", depends_on=[])]
    plan = Plan(run_id="abc", original_prompt="do stuff", agent_count=3,
                complexity_score=15, tasks=tasks)
    assert len(plan.tasks) == 1
    assert plan.agent_count == 3


def test_message_defaults():
    msg = Message(id="m1", type="DISPATCH", from_agent="manager",
                  to_agent="agent-001", payload={"task_id": "t1"})
    assert msg.processed is False
    assert isinstance(msg.created_at, datetime)


def test_agent_record_defaults():
    agent = AgentRecord(id="a1", run_id="r1", worktree_path="/tmp/wt",
                        branch="galaxy/r1/a1", task_id="t1")
    assert agent.status == "idle"
    assert agent.pid is None
    assert isinstance(agent.last_heartbeat, datetime)


def test_run_record_defaults():
    run = RunRecord(id="r1", prompt="do stuff", agent_count=3, complexity_score=15)
    assert run.status == "running"
    assert run.completed_at is None
    assert isinstance(run.started_at, datetime)
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_models.py -v
```

Expected: `ImportError: cannot import name 'SubTask' from 'galaxy.models'`

- [ ] **Step 3: Create `galaxy/models.py`**

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class SubTask:
    id: str
    description: str
    depends_on: list[str]
    status: Literal["pending", "in_progress", "complete", "failed"] = "pending"
    assigned_agent: str | None = None
    worktree_path: str | None = None
    branch: str | None = None


@dataclass
class Plan:
    run_id: str
    original_prompt: str
    agent_count: int
    complexity_score: int
    tasks: list[SubTask]


@dataclass
class Message:
    id: str
    type: Literal["DISPATCH", "PROGRESS", "COMPLETE", "ERROR", "ESCALATE", "SYNC"]
    from_agent: str
    to_agent: str
    payload: dict
    created_at: datetime = field(default_factory=datetime.utcnow)
    processed: bool = False


@dataclass
class AgentRecord:
    id: str
    run_id: str
    worktree_path: str
    branch: str
    task_id: str
    pid: int | None = None
    status: Literal["idle", "working", "done", "failed"] = "idle"
    last_heartbeat: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RunRecord:
    id: str
    prompt: str
    agent_count: int
    complexity_score: int
    status: Literal["running", "complete", "failed"] = "running"
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
pytest tests/test_models.py -v
```

Expected: `6 passed`

- [ ] **Step 5: Commit**

```bash
git add galaxy/models.py tests/test_models.py
git commit -m "feat: data models with TDD"
```

---

## Task 3: Taskbox (SQLite Message Bus)

**Files:**
- Create: `galaxy/taskbox.py`
- Create: `tests/test_taskbox.py`

- [ ] **Step 1: Write failing tests in `tests/test_taskbox.py`**

```python
import pytest
from datetime import datetime
from galaxy.taskbox import Taskbox
from galaxy.models import SubTask, Message, AgentRecord, RunRecord


def test_init_creates_tables(db):
    conn = db._conn()
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert {"tasks", "messages", "agents", "runs"}.issubset(tables)


def test_save_and_get_task(db):
    task = SubTask(id="t1", description="Do thing", depends_on=["t0"])
    db.save_task(task, "run1")
    tasks = db.get_tasks("run1")
    assert len(tasks) == 1
    assert tasks[0].id == "t1"
    assert tasks[0].depends_on == ["t0"]


def test_update_task_status(db):
    db.save_task(SubTask(id="t1", description="Do thing", depends_on=[]), "run1")
    db.update_task_status("t1", "complete")
    tasks = db.get_tasks("run1")
    assert tasks[0].status == "complete"


def test_get_pending_tasks(db):
    db.save_task(SubTask(id="t1", description="A", depends_on=[]), "run1")
    db.save_task(SubTask(id="t2", description="B", depends_on=[]), "run1")
    db.update_task_status("t1", "complete")
    pending = db.get_pending_tasks("run1")
    assert len(pending) == 1
    assert pending[0].id == "t2"


def test_get_completed_task_ids(db):
    db.save_task(SubTask(id="t1", description="A", depends_on=[]), "run1")
    db.save_task(SubTask(id="t2", description="B", depends_on=[]), "run1")
    db.update_task_status("t1", "complete")
    completed = db.get_completed_task_ids("run1")
    assert completed == {"t1"}


def test_message_roundtrip(db):
    msg = Message(id="m1", type="COMPLETE", from_agent="a1", to_agent="manager",
                  payload={"task_id": "t1"}, created_at=datetime.utcnow())
    db.send_message(msg)
    messages = db.get_unprocessed_messages("manager")
    assert len(messages) == 1
    assert messages[0].type == "COMPLETE"
    assert messages[0].payload == {"task_id": "t1"}


def test_mark_message_processed(db):
    msg = Message(id="m1", type="COMPLETE", from_agent="a1", to_agent="manager",
                  payload={}, created_at=datetime.utcnow())
    db.send_message(msg)
    db.mark_message_processed("m1")
    messages = db.get_unprocessed_messages("manager")
    assert len(messages) == 0


def test_save_and_get_run(db):
    run = RunRecord(id="r1", prompt="do stuff", agent_count=3, complexity_score=15)
    db.save_run(run)
    retrieved = db.get_run("r1")
    assert retrieved is not None
    assert retrieved.prompt == "do stuff"
    assert retrieved.status == "running"


def test_get_run_missing(db):
    assert db.get_run("nope") is None


def test_save_and_get_agents(db):
    agent = AgentRecord(id="a1", run_id="r1", worktree_path="/tmp/wt",
                        branch="galaxy/r1/a1", task_id="t1")
    db.save_agent(agent)
    agents = db.get_agents("r1")
    assert len(agents) == 1
    assert agents[0].id == "a1"


def test_update_agent_status(db):
    agent = AgentRecord(id="a1", run_id="r1", worktree_path="/tmp/wt",
                        branch="galaxy/r1/a1", task_id="t1")
    db.save_agent(agent)
    db.update_agent_status("a1", "working", pid=12345)
    agents = db.get_agents("r1")
    assert agents[0].status == "working"
    assert agents[0].pid == 12345
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_taskbox.py -v
```

Expected: `ImportError: cannot import name 'Taskbox' from 'galaxy.taskbox'`

- [ ] **Step 3: Create `galaxy/taskbox.py`**

```python
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .models import AgentRecord, Message, RunRecord, SubTask


class Taskbox:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    description TEXT NOT NULL,
                    depends_on TEXT NOT NULL DEFAULT '[]',
                    assigned_agent TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    worktree_path TEXT,
                    branch TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    from_agent TEXT NOT NULL,
                    to_agent TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    processed INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    worktree_path TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    pid INTEGER,
                    status TEXT NOT NULL DEFAULT 'idle',
                    last_heartbeat TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    prompt TEXT NOT NULL,
                    agent_count INTEGER NOT NULL,
                    complexity_score INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'running',
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                );
            """)

    def save_run(self, run: RunRecord) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?)",
                (
                    run.id, run.prompt, run.agent_count, run.complexity_score,
                    run.status, run.started_at.isoformat(),
                    run.completed_at.isoformat() if run.completed_at else None,
                ),
            )

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return None
        return RunRecord(
            id=row["id"], prompt=row["prompt"], agent_count=row["agent_count"],
            complexity_score=row["complexity_score"], status=row["status"],
            started_at=datetime.fromisoformat(row["started_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
        )

    def save_task(self, task: SubTask, run_id: str) -> None:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    task.id, run_id, task.description, json.dumps(task.depends_on),
                    task.assigned_agent, task.status, task.worktree_path, task.branch,
                    now, now,
                ),
            )

    def update_task_status(self, task_id: str, status: str, **kwargs: object) -> None:
        sets = ["status=?", "updated_at=?"]
        params: list[object] = [status, datetime.utcnow().isoformat()]
        for key, val in kwargs.items():
            sets.append(f"{key}=?")
            params.append(val)
        params.append(task_id)
        with self._conn() as conn:
            conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", params)

    def get_tasks(self, run_id: str) -> list[SubTask]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM tasks WHERE run_id=?", (run_id,)).fetchall()
        return [
            SubTask(
                id=r["id"], description=r["description"],
                depends_on=json.loads(r["depends_on"]),
                status=r["status"], assigned_agent=r["assigned_agent"],
                worktree_path=r["worktree_path"], branch=r["branch"],
            )
            for r in rows
        ]

    def get_pending_tasks(self, run_id: str) -> list[SubTask]:
        return [t for t in self.get_tasks(run_id) if t.status == "pending"]

    def get_completed_task_ids(self, run_id: str) -> set[str]:
        return {t.id for t in self.get_tasks(run_id) if t.status == "complete"}

    def send_message(self, msg: Message) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO messages VALUES (?,?,?,?,?,?,?)",
                (
                    msg.id, msg.type, msg.from_agent, msg.to_agent,
                    json.dumps(msg.payload), msg.created_at.isoformat(), 0,
                ),
            )

    def get_unprocessed_messages(self, to_agent: str) -> list[Message]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE to_agent=? AND processed=0 ORDER BY created_at",
                (to_agent,),
            ).fetchall()
        return [
            Message(
                id=r["id"], type=r["type"], from_agent=r["from_agent"],
                to_agent=r["to_agent"], payload=json.loads(r["payload"]),
                created_at=datetime.fromisoformat(r["created_at"]),
                processed=bool(r["processed"]),
            )
            for r in rows
        ]

    def mark_message_processed(self, msg_id: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE messages SET processed=1 WHERE id=?", (msg_id,))

    def save_agent(self, agent: AgentRecord) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO agents VALUES (?,?,?,?,?,?,?,?)",
                (
                    agent.id, agent.run_id, agent.worktree_path, agent.branch,
                    agent.task_id, agent.pid, agent.status,
                    agent.last_heartbeat.isoformat(),
                ),
            )

    def update_agent_status(self, agent_id: str, status: str, pid: int | None = None) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE agents SET status=?, last_heartbeat=?, pid=? WHERE id=?",
                (status, datetime.utcnow().isoformat(), pid, agent_id),
            )

    def get_agents(self, run_id: str) -> list[AgentRecord]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM agents WHERE run_id=?", (run_id,)).fetchall()
        return [
            AgentRecord(
                id=r["id"], run_id=r["run_id"], worktree_path=r["worktree_path"],
                branch=r["branch"], task_id=r["task_id"], pid=r["pid"],
                status=r["status"],
                last_heartbeat=datetime.fromisoformat(r["last_heartbeat"]),
            )
            for r in rows
        ]
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
pytest tests/test_taskbox.py -v
```

Expected: `11 passed`

- [ ] **Step 5: Commit**

```bash
git add galaxy/taskbox.py tests/test_taskbox.py
git commit -m "feat: SQLite taskbox message bus with TDD"
```

---

## Task 4: Workspace Manager

**Files:**
- Create: `galaxy/workspace.py`
- Create: `tests/test_workspace.py`

- [ ] **Step 1: Write failing tests in `tests/test_workspace.py`**

```python
import subprocess
import pytest
from pathlib import Path
from galaxy.workspace import (
    detect_verify_command,
    create_worktree,
    delete_worktree,
    get_config,
    init_galaxy,
    is_initialized,
    list_worktrees,
    symlink_env_files,
)


def test_is_initialized_false(git_repo):
    assert not is_initialized(git_repo)


def test_init_galaxy(git_repo):
    galaxy_dir = init_galaxy(git_repo)
    assert is_initialized(git_repo)
    assert (galaxy_dir / "worktrees").exists()
    assert (galaxy_dir / "runs").exists()
    assert (galaxy_dir / "config.json").exists()


def test_init_galaxy_idempotent(git_repo):
    init_galaxy(git_repo)
    init_galaxy(git_repo)
    assert is_initialized(git_repo)


def test_get_config(git_repo):
    init_galaxy(git_repo)
    config = get_config(git_repo)
    assert "worker_timeout_seconds" in config
    assert config["max_concurrent_workers"] == 20


def test_create_and_delete_worktree(git_repo):
    init_galaxy(git_repo)
    wt_path, branch = create_worktree(git_repo, "run123", "agent-001")
    assert wt_path.exists()
    assert branch == "galaxy/run123/agent-001"
    delete_worktree(git_repo, wt_path)
    assert not wt_path.exists()


def test_list_worktrees_includes_galaxy_branch(git_repo):
    init_galaxy(git_repo)
    create_worktree(git_repo, "run123", "agent-001")
    worktrees = list_worktrees(git_repo)
    branches = [w.get("branch", "") for w in worktrees]
    assert any("galaxy/run123/agent-001" in b for b in branches)


def test_symlink_env_files(git_repo):
    init_galaxy(git_repo)
    (git_repo / ".env").write_text("KEY=val")
    wt_path, _ = create_worktree(git_repo, "run123", "agent-001")
    linked = symlink_env_files(wt_path, git_repo)
    assert any(str(p).endswith(".env") for p in linked)
    assert (wt_path / ".env").is_symlink()


def test_detect_verify_command_pytest(git_repo):
    (git_repo / "pyproject.toml").write_text("[tool.pytest]\n")
    (git_repo / "tests").mkdir()
    assert detect_verify_command(git_repo) == "pytest"


def test_detect_verify_command_npm(git_repo):
    (git_repo / "package.json").write_text('{"scripts": {"test": "jest"}}')
    assert detect_verify_command(git_repo) == "npm test"


def test_detect_verify_command_none(git_repo):
    assert detect_verify_command(git_repo) is None
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_workspace.py -v
```

Expected: `ImportError: cannot import name 'is_initialized' from 'galaxy.workspace'`

- [ ] **Step 3: Create `galaxy/workspace.py`**

```python
import json
import subprocess
from pathlib import Path

_GALAXY_DIR = ".galaxy"


def is_initialized(repo_path: Path) -> bool:
    return (repo_path / _GALAXY_DIR).exists()


def init_galaxy(repo_path: Path) -> Path:
    galaxy_dir = repo_path / _GALAXY_DIR
    (galaxy_dir / "worktrees").mkdir(parents=True, exist_ok=True)
    (galaxy_dir / "runs").mkdir(parents=True, exist_ok=True)
    config_path = galaxy_dir / "config.json"
    if not config_path.exists():
        config_path.write_text(
            json.dumps(
                {
                    "verify_command": None,
                    "default_agent_count": None,
                    "worker_timeout_seconds": 120,
                    "anthropic_model": "claude-opus-4-7",
                    "max_concurrent_workers": 20,
                },
                indent=2,
            )
        )
    return galaxy_dir


def get_config(repo_path: Path) -> dict:
    config_path = repo_path / _GALAXY_DIR / "config.json"
    if config_path.exists():
        return json.loads(config_path.read_text())
    return {}


def create_worktree(repo_path: Path, run_id: str, agent_id: str) -> tuple[Path, str]:
    branch = f"galaxy/{run_id}/{agent_id}"
    worktree_path = repo_path / _GALAXY_DIR / "worktrees" / agent_id
    subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(worktree_path)],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )
    return worktree_path, branch


def delete_worktree(repo_path: Path, worktree_path: Path) -> None:
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_path)],
        cwd=repo_path,
        check=True,
        capture_output=True,
    )


def list_worktrees(repo_path: Path) -> list[dict]:
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo_path,
        check=True,
        capture_output=True,
        text=True,
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

- [ ] **Step 4: Run tests to confirm pass**

```bash
pytest tests/test_workspace.py -v
```

Expected: `10 passed`

- [ ] **Step 5: Commit**

```bash
git add galaxy/workspace.py tests/test_workspace.py
git commit -m "feat: git worktree workspace manager with TDD"
```

---

## Task 5: Planner (Anthropic API)

**Files:**
- Create: `galaxy/planner.py`
- Create: `tests/test_planner.py`

- [ ] **Step 1: Write failing tests in `tests/test_planner.py`**

```python
import json
import pytest
from unittest.mock import MagicMock, patch
from galaxy.models import Plan, SubTask
from galaxy.planner import compute_agent_count, plan_task

MOCK_API_RESPONSE = json.dumps({
    "complexity_score": 25,
    "agent_count": 6,
    "tasks": [
        {"id": "t1", "description": "Set up project structure", "depends_on": []},
        {"id": "t2", "description": "Implement auth module", "depends_on": ["t1"]},
        {"id": "t3", "description": "Write tests", "depends_on": ["t2"]},
    ],
})


def _mock_anthropic(response_text: str):
    mock_content = MagicMock()
    mock_content.text = response_text
    mock_response = MagicMock()
    mock_response.content = [mock_content]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    return mock_client


def test_compute_agent_count_trivial():
    assert compute_agent_count(10) == 3


def test_compute_agent_count_small():
    count = compute_agent_count(30)
    assert 5 <= count <= 10


def test_compute_agent_count_medium():
    count = compute_agent_count(50)
    assert 10 <= count <= 20


def test_compute_agent_count_large():
    count = compute_agent_count(70)
    assert 20 <= count <= 50


def test_compute_agent_count_very_large():
    assert compute_agent_count(90) >= 50


def test_plan_task_returns_plan():
    with patch("galaxy.planner.Anthropic", return_value=_mock_anthropic(MOCK_API_RESPONSE)):
        plan = plan_task("Build a REST API")

    assert isinstance(plan, Plan)
    assert plan.complexity_score == 25
    assert len(plan.tasks) == 3
    assert plan.tasks[0].id == "t1"
    assert plan.tasks[1].depends_on == ["t1"]


def test_plan_task_agent_count_override():
    with patch("galaxy.planner.Anthropic", return_value=_mock_anthropic(MOCK_API_RESPONSE)):
        plan = plan_task("Build a REST API", agent_count_override=42)

    assert plan.agent_count == 42


def test_plan_task_handles_json_in_code_block():
    wrapped = f"```json\n{MOCK_API_RESPONSE}\n```"
    with patch("galaxy.planner.Anthropic", return_value=_mock_anthropic(wrapped)):
        plan = plan_task("Build a REST API")

    assert len(plan.tasks) == 3


def test_plan_task_subtask_types():
    with patch("galaxy.planner.Anthropic", return_value=_mock_anthropic(MOCK_API_RESPONSE)):
        plan = plan_task("Build a REST API")

    for task in plan.tasks:
        assert isinstance(task, SubTask)
        assert task.status == "pending"
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_planner.py -v
```

Expected: `ImportError: cannot import name 'compute_agent_count' from 'galaxy.planner'`

- [ ] **Step 3: Create `galaxy/planner.py`**

```python
import json
import re
import uuid

from anthropic import Anthropic

from .models import Plan, SubTask

_SYSTEM_PROMPT = """You are a software engineering task decomposition expert.
Given a coding task, assess complexity (1-100) and break it into atomic subtasks.

Agent count guidelines:
- Score 1-20: 3 agents (bug fix, trivial change)
- Score 21-40: 5-10 agents (small feature)
- Score 41-60: 10-20 agents (medium feature with tests)
- Score 61-80: 20-50 agents (multi-module feature)
- Score 81-100: 50-100 agents (full project)

Respond ONLY with valid JSON:
{
  "complexity_score": <int 1-100>,
  "agent_count": <int>,
  "tasks": [
    {"id": "t1", "description": "<actionable task>", "depends_on": []}
  ]
}

Rules:
- Each task must be independently executable by one AI coding agent
- Tasks must form a valid DAG (no cycles)
- Include file names in descriptions where possible
- depends_on lists IDs of prerequisite tasks
"""


def compute_agent_count(complexity_score: int) -> int:
    if complexity_score <= 20:
        return 3
    if complexity_score <= 40:
        return max(5, complexity_score // 5)
    if complexity_score <= 60:
        return max(10, complexity_score // 4)
    if complexity_score <= 80:
        return max(20, complexity_score // 2)
    return max(50, complexity_score)


def plan_task(
    prompt: str,
    model: str = "claude-opus-4-7",
    agent_count_override: int | None = None,
) -> Plan:
    client = Anthropic()
    run_id = str(uuid.uuid4())[:8]

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Task: {prompt}"}],
    )

    raw = response.content[0].text.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
    if match:
        raw = match.group(1)

    data = json.loads(raw)

    agent_count = agent_count_override or compute_agent_count(data["complexity_score"])

    tasks = [
        SubTask(
            id=t["id"],
            description=t["description"],
            depends_on=t.get("depends_on", []),
        )
        for t in data["tasks"]
    ]

    return Plan(
        run_id=run_id,
        original_prompt=prompt,
        agent_count=agent_count,
        complexity_score=data["complexity_score"],
        tasks=tasks,
    )
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
pytest tests/test_planner.py -v
```

Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add galaxy/planner.py tests/test_planner.py
git commit -m "feat: Anthropic API planner with TDD"
```

---

## Task 6: Worker (Async Subprocess)

**Files:**
- Create: `galaxy/worker.py`
- Create: `tests/test_worker.py`

- [ ] **Step 1: Write failing tests in `tests/test_worker.py`**

```python
import asyncio
import stat
import pytest
from galaxy.models import AgentRecord
from galaxy.worker import run_worker


def make_agent(db, worktree):
    agent = AgentRecord(
        id="a1", run_id="r1", worktree_path=str(worktree),
        branch="galaxy/r1/a1", task_id="t1",
    )
    db.save_agent(agent)
    return agent


@pytest.mark.asyncio
async def test_worker_sends_complete_on_success(db, tmp_path):
    make_agent(db, tmp_path)
    await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do the thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, claude_cmd="true",
    )
    messages = db.get_unprocessed_messages("manager")
    assert any(m.type == "COMPLETE" for m in messages)


@pytest.mark.asyncio
async def test_worker_sends_error_on_failure(db, tmp_path):
    make_agent(db, tmp_path)
    await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do the thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, claude_cmd="false",
    )
    messages = db.get_unprocessed_messages("manager")
    assert any(m.type == "ERROR" for m in messages)


@pytest.mark.asyncio
async def test_worker_writes_task_md(db, tmp_path):
    make_agent(db, tmp_path)
    await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Build the auth module",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, claude_cmd="true",
    )
    task_md = tmp_path / "TASK.md"
    assert task_md.exists()
    content = task_md.read_text()
    assert "Build the auth module" in content
    assert "a1" in content


@pytest.mark.asyncio
async def test_worker_timeout_sends_error(db, tmp_path):
    make_agent(db, tmp_path)
    # Create a script that sleeps longer than timeout
    script = tmp_path / "slow.sh"
    script.write_text("#!/bin/sh\nsleep 100\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do the thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=1, claude_cmd=str(script),
    )
    messages = db.get_unprocessed_messages("manager")
    assert any(m.type == "ERROR" for m in messages)


@pytest.mark.asyncio
async def test_worker_updates_agent_status_to_working(db, tmp_path):
    make_agent(db, tmp_path)
    await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do the thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, claude_cmd="true",
    )
    agents = db.get_agents("r1")
    assert agents[0].status in ("done", "failed")
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_worker.py -v
```

Expected: `ImportError: cannot import name 'run_worker' from 'galaxy.worker'`

- [ ] **Step 3: Create `galaxy/worker.py`**

```python
import asyncio
import uuid
from datetime import datetime
from pathlib import Path

from .models import Message
from .taskbox import Taskbox

_TASK_TEMPLATE = """\
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


async def run_worker(
    agent_id: str,
    run_id: str,
    task_id: str,
    task_description: str,
    worktree_path: Path,
    taskbox: Taskbox,
    timeout: int = 120,
    claude_cmd: str = "claude",
) -> None:
    short_desc = task_description[:50].replace("\n", " ")
    (worktree_path / "TASK.md").write_text(
        _TASK_TEMPLATE.format(
            description=task_description,
            run_id=run_id,
            agent_id=agent_id,
            short_desc=short_desc,
        )
    )

    taskbox.update_agent_status(agent_id, "working")

    try:
        proc = await asyncio.create_subprocess_exec(
            claude_cmd,
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

- [ ] **Step 4: Run tests to confirm pass**

```bash
pytest tests/test_worker.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add galaxy/worker.py tests/test_worker.py
git commit -m "feat: async worker subprocess wrapper with TDD"
```

---

## Task 7: Integration Engine

**Files:**
- Create: `galaxy/integration.py`
- Create: `tests/test_integration.py`

- [ ] **Step 1: Write failing tests in `tests/test_integration.py`**

```python
import subprocess
import pytest
from pathlib import Path
from galaxy.integration import (
    detect_verify_command,
    integrate_worktree,
    merge_branch,
    run_verify,
)


def test_detect_verify_pytest(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[tool.pytest]\n")
    (tmp_path / "tests").mkdir()
    assert detect_verify_command(tmp_path) == "pytest"


def test_detect_verify_npm(tmp_path):
    (tmp_path / "package.json").write_text("{}")
    assert detect_verify_command(tmp_path) == "npm test"


def test_detect_verify_none(tmp_path):
    assert detect_verify_command(tmp_path) is None


def test_run_verify_passing_command(tmp_path):
    passed, output = run_verify(tmp_path, verify_cmd="true")
    assert passed is True


def test_run_verify_failing_command(tmp_path):
    passed, output = run_verify(tmp_path, verify_cmd="false")
    assert passed is False


def test_run_verify_no_command_skips(tmp_path):
    passed, output = run_verify(tmp_path, verify_cmd=None)
    assert passed is True
    assert "skipping" in output


def test_merge_branch(git_repo):
    branch = "feature/test-merge"
    subprocess.run(["git", "checkout", "-b", branch], cwd=git_repo,
                   check=True, capture_output=True)
    (git_repo / "new_file.txt").write_text("content")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add file"], cwd=git_repo,
                   check=True, capture_output=True)
    # Return to default branch (git init uses 'master' or 'main')
    result = subprocess.run(["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
                            cwd=git_repo, capture_output=True)
    default = "master"
    for candidate in ("main", "master"):
        r = subprocess.run(["git", "checkout", candidate], cwd=git_repo,
                           capture_output=True)
        if r.returncode == 0:
            default = candidate
            break

    success, output = merge_branch(git_repo, branch)
    assert success is True
    assert (git_repo / "new_file.txt").exists()


def test_integrate_worktree_passes_verify(git_repo):
    branch = "feature/integration-test"
    subprocess.run(["git", "checkout", "-b", branch], cwd=git_repo,
                   check=True, capture_output=True)
    (git_repo / "feature.txt").write_text("feature content")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "add feature"], cwd=git_repo,
                   check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-"], cwd=git_repo,
                   check=True, capture_output=True)

    success, output = integrate_worktree(git_repo, git_repo, branch, verify_cmd="true")
    assert success is True
    assert (git_repo / "feature.txt").exists()


def test_integrate_worktree_fails_on_bad_verify(git_repo):
    branch = "feature/bad-verify"
    subprocess.run(["git", "checkout", "-b", branch], cwd=git_repo,
                   check=True, capture_output=True)
    (git_repo / "bad.txt").write_text("bad")
    subprocess.run(["git", "add", "."], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "bad"], cwd=git_repo,
                   check=True, capture_output=True)
    subprocess.run(["git", "checkout", "-"], cwd=git_repo,
                   check=True, capture_output=True)

    success, output = integrate_worktree(git_repo, git_repo, branch, verify_cmd="false")
    assert success is False
    assert "verify failed" in output
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_integration.py -v
```

Expected: `ImportError: cannot import name 'detect_verify_command' from 'galaxy.integration'`

- [ ] **Step 3: Create `galaxy/integration.py`**

```python
import subprocess
from pathlib import Path


def detect_verify_command(path: Path) -> str | None:
    if (path / "pyproject.toml").exists() and (path / "tests").exists():
        return "pytest"
    if (path / "package.json").exists():
        return "npm test"
    if (path / "Makefile").exists():
        return "make test"
    return None


def run_verify(path: Path, verify_cmd: str | None = None) -> tuple[bool, str]:
    cmd = verify_cmd or detect_verify_command(path)
    if not cmd:
        return True, "no verify command found, skipping"
    result = subprocess.run(
        cmd.split(),
        cwd=path,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, result.stdout + result.stderr


def merge_branch(repo_path: Path, branch: str) -> tuple[bool, str]:
    result = subprocess.run(
        ["git", "merge", "--no-ff", branch, "-m", f"galaxy: merge {branch}"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0, result.stdout + result.stderr


def integrate_worktree(
    repo_path: Path,
    worktree_path: Path,
    branch: str,
    verify_cmd: str | None = None,
) -> tuple[bool, str]:
    passed, verify_output = run_verify(worktree_path, verify_cmd)
    if not passed:
        return False, f"verify failed:\n{verify_output}"
    merged, merge_output = merge_branch(repo_path, branch)
    if not merged:
        return False, f"merge failed:\n{merge_output}"
    return True, f"integrated {branch}\n{verify_output}\n{merge_output}"
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
pytest tests/test_integration.py -v
```

Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add galaxy/integration.py tests/test_integration.py
git commit -m "feat: integration engine (verify + merge) with TDD"
```

---

## Task 8: Manager (asyncio Orchestrator)

**Files:**
- Create: `galaxy/manager.py`
- Create: `tests/test_manager.py`

- [ ] **Step 1: Write failing tests in `tests/test_manager.py`**

```python
import asyncio
import uuid
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from galaxy.manager import run_manager
from galaxy.models import Message, Plan, SubTask
from galaxy.workspace import init_galaxy


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


def _fake_create(git_repo):
    def _create(repo_path, run_id, agent_id):
        p = git_repo / f".galaxy/worktrees/{agent_id}"
        p.mkdir(parents=True, exist_ok=True)
        return p, f"galaxy/{run_id}/{agent_id}"
    return _create


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


@pytest.mark.asyncio
async def test_manager_single_task_success(db, git_repo):
    init_galaxy(git_repo)
    plan = _make_plan()

    with patch("galaxy.manager.run_worker", new_callable=AsyncMock, side_effect=_make_fake_worker(db)), \
         patch("galaxy.manager.integrate_worktree", return_value=(True, "ok")), \
         patch("galaxy.manager.create_worktree", side_effect=_fake_create(git_repo)), \
         patch("galaxy.manager.symlink_env_files"):
        result = await run_manager(plan, git_repo, db, verify_cmd="true")

    assert result["status"] == "complete"
    assert result["completed"] == 1
    assert result["failed"] == 0


@pytest.mark.asyncio
async def test_manager_task_dependency_order(db, git_repo):
    init_galaxy(git_repo)
    tasks = [
        SubTask(id="t1", description="First", depends_on=[]),
        SubTask(id="t2", description="Second", depends_on=["t1"]),
    ]
    plan = _make_plan(tasks, run_id="deptest")
    dispatch_order = []

    async def _ordered_worker(**kwargs):
        dispatch_order.append(kwargs["task_id"])
        db.send_message(Message(
            id=str(uuid.uuid4()), type="COMPLETE",
            from_agent=kwargs["agent_id"], to_agent="manager",
            payload={"task_id": kwargs["task_id"]},
            created_at=datetime.utcnow(),
        ))
        db.update_agent_status(kwargs["agent_id"], "done")

    with patch("galaxy.manager.run_worker", new_callable=AsyncMock, side_effect=_ordered_worker), \
         patch("galaxy.manager.integrate_worktree", return_value=(True, "ok")), \
         patch("galaxy.manager.create_worktree", side_effect=_fake_create(git_repo)), \
         patch("galaxy.manager.symlink_env_files"):
        result = await run_manager(plan, git_repo, db, verify_cmd="true")

    assert result["status"] == "complete"
    assert result["completed"] == 2
    assert dispatch_order.index("t1") < dispatch_order.index("t2")


@pytest.mark.asyncio
async def test_manager_failed_integration_marks_task_failed(db, git_repo):
    init_galaxy(git_repo)
    plan = _make_plan()

    with patch("galaxy.manager.run_worker", new_callable=AsyncMock, side_effect=_make_fake_worker(db)), \
         patch("galaxy.manager.integrate_worktree", return_value=(False, "tests failed")), \
         patch("galaxy.manager.create_worktree", side_effect=_fake_create(git_repo)), \
         patch("galaxy.manager.symlink_env_files"):
        result = await run_manager(plan, git_repo, db, verify_cmd="true")

    assert result["status"] == "failed"
    assert result["failed"] == 1


@pytest.mark.asyncio
async def test_manager_run_saved_to_taskbox(db, git_repo):
    init_galaxy(git_repo)
    plan = _make_plan()

    with patch("galaxy.manager.run_worker", new_callable=AsyncMock, side_effect=_make_fake_worker(db)), \
         patch("galaxy.manager.integrate_worktree", return_value=(True, "ok")), \
         patch("galaxy.manager.create_worktree", side_effect=_fake_create(git_repo)), \
         patch("galaxy.manager.symlink_env_files"):
        await run_manager(plan, git_repo, db, verify_cmd="true")

    run_rec = db.get_run(plan.run_id)
    assert run_rec is not None
    assert run_rec.status == "complete"


@pytest.mark.asyncio
async def test_manager_dependent_task_fails_when_dep_fails(db, git_repo):
    init_galaxy(git_repo)
    tasks = [
        SubTask(id="t1", description="First", depends_on=[]),
        SubTask(id="t2", description="Blocked by t1", depends_on=["t1"]),
    ]
    plan = _make_plan(tasks, run_id="failtest")

    async def _failing_worker(**kwargs):
        db.send_message(Message(
            id=str(uuid.uuid4()), type="COMPLETE",
            from_agent=kwargs["agent_id"], to_agent="manager",
            payload={"task_id": kwargs["task_id"]},
            created_at=datetime.utcnow(),
        ))

    with patch("galaxy.manager.run_worker", new_callable=AsyncMock, side_effect=_failing_worker), \
         patch("galaxy.manager.integrate_worktree", return_value=(False, "tests failed")), \
         patch("galaxy.manager.create_worktree", side_effect=_fake_create(git_repo)), \
         patch("galaxy.manager.symlink_env_files"):
        result = await run_manager(plan, git_repo, db, verify_cmd="true")

    assert result["failed"] >= 1
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_manager.py -v
```

Expected: `ImportError: cannot import name 'run_manager' from 'galaxy.manager'`

- [ ] **Step 3: Create `galaxy/manager.py`**

```python
import asyncio
import uuid
from datetime import datetime
from pathlib import Path

from .integration import integrate_worktree
from .models import AgentRecord, Plan, RunRecord
from .taskbox import Taskbox
from .worker import run_worker
from .workspace import create_worktree, symlink_env_files


async def run_manager(
    plan: Plan,
    repo_path: Path,
    taskbox: Taskbox,
    max_concurrent: int = 20,
    verify_cmd: str | None = None,
    claude_cmd: str = "claude",
    worker_timeout: int = 120,
) -> dict:
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
    in_flight: dict[str, asyncio.Task] = {}  # task_id -> asyncio.Task
    task_to_agent: dict[str, str] = {}
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _dispatch(subtask) -> None:
        agent_id = f"agent-{str(uuid.uuid4())[:6]}"
        worktree_path, branch = create_worktree(repo_path, plan.run_id, agent_id)
        symlink_env_files(worktree_path, repo_path)

        taskbox.save_agent(
            AgentRecord(
                id=agent_id, run_id=plan.run_id,
                worktree_path=str(worktree_path), branch=branch,
                task_id=subtask.id, last_heartbeat=datetime.utcnow(),
            )
        )
        taskbox.update_task_status(
            subtask.id, "in_progress",
            assigned_agent=agent_id,
            worktree_path=str(worktree_path),
            branch=branch,
        )
        task_to_agent[subtask.id] = agent_id

        async with semaphore:
            await run_worker(
                agent_id=agent_id, run_id=plan.run_id,
                task_id=subtask.id, task_description=subtask.description,
                worktree_path=worktree_path, taskbox=taskbox,
                timeout=worker_timeout, claude_cmd=claude_cmd,
            )

    while len(completed) + len(failed) < len(all_ids):
        # Dispatch all newly unblocked tasks
        dispatchable = [
            t for t in plan.tasks
            if t.id not in completed
            and t.id not in failed
            and t.id not in task_to_agent
            and all(dep in completed for dep in t.depends_on)
        ]
        for subtask in dispatchable:
            in_flight[subtask.id] = asyncio.create_task(_dispatch(subtask))

        # Process messages
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
                    ok, out = integrate_worktree(
                        repo_path, Path(agent_rec.worktree_path),
                        agent_rec.branch, verify_cmd,
                    )
                    if ok:
                        completed.add(task_id)
                        taskbox.update_task_status(task_id, "complete")
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

        # Propagate failures to blocked dependents
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

        if in_flight:
            await asyncio.sleep(0.1)
        elif dispatchable:
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

    return {
        "run_id": plan.run_id,
        "status": status,
        "completed": len(completed),
        "failed": len(failed),
        "total": len(all_ids),
    }
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
pytest tests/test_manager.py -v
```

Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add galaxy/manager.py tests/test_manager.py
git commit -m "feat: asyncio manager orchestrator with TDD"
```

---

## Task 9: CLI (Click)

**Files:**
- Create: `galaxy/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests in `tests/test_cli.py`**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from galaxy.cli import main
from galaxy.models import Plan, SubTask


def _simple_plan():
    return Plan(
        run_id="abc123",
        original_prompt="do stuff",
        agent_count=3,
        complexity_score=15,
        tasks=[SubTask(id="t1", description="task", depends_on=[])],
    )


def test_init_command(runner, git_repo):
    result = runner.invoke(main, ["init", str(git_repo)])
    assert result.exit_code == 0
    assert "Initialized" in result.output
    assert (git_repo / ".galaxy").exists()


def test_init_command_idempotent(runner, git_repo):
    runner.invoke(main, ["init", str(git_repo)])
    result = runner.invoke(main, ["init", str(git_repo)])
    assert result.exit_code == 0
    assert "already initialized" in result.output


def test_status_not_initialized(runner, git_repo):
    result = runner.invoke(main, ["status", "--repo", str(git_repo)])
    assert result.exit_code == 0
    assert "not initialized" in result.output


def test_status_initialized_no_runs(runner, git_repo):
    runner.invoke(main, ["init", str(git_repo)])
    result = runner.invoke(main, ["status", "--repo", str(git_repo)])
    assert result.exit_code == 0
    assert "worktree" in result.output.lower()


def test_clean_no_worktrees(runner, git_repo):
    runner.invoke(main, ["init", str(git_repo)])
    result = runner.invoke(main, ["clean", "--repo", str(git_repo)])
    assert result.exit_code == 0
    assert "No galaxy worktrees" in result.output


def test_run_requires_prompt_or_file(runner, git_repo):
    result = runner.invoke(main, ["run", "--repo", str(git_repo)])
    assert result.exit_code != 0


def test_run_with_mock_planner_and_manager(runner, git_repo):
    with patch("galaxy.cli.plan_task", return_value=_simple_plan()) as mock_plan, \
         patch("galaxy.cli.run_manager", new_callable=AsyncMock,
               return_value={"run_id": "abc123", "status": "complete",
                             "completed": 1, "failed": 0, "total": 1}):
        result = runner.invoke(main, [
            "run", "do stuff", "--repo", str(git_repo),
        ])
    assert result.exit_code == 0
    assert "complete" in result.output.lower()


def test_run_from_file(runner, git_repo, tmp_path):
    task_file = tmp_path / "tasks.md"
    task_file.write_text("# Tasks\n\nBuild the auth module\n")

    with patch("galaxy.cli.plan_task", return_value=_simple_plan()), \
         patch("galaxy.cli.run_manager", new_callable=AsyncMock,
               return_value={"run_id": "abc123", "status": "complete",
                             "completed": 1, "failed": 0, "total": 1}):
        result = runner.invoke(main, [
            "run", "--file", str(task_file), "--repo", str(git_repo),
        ])
    assert result.exit_code == 0
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_cli.py -v
```

Expected: `ImportError: cannot import name 'main' from 'galaxy.cli'`

- [ ] **Step 3: Create `galaxy/cli.py`**

```python
import asyncio
from pathlib import Path

import click

from .integration import detect_verify_command
from .manager import run_manager
from .planner import plan_task
from .taskbox import Taskbox
from .workspace import get_config, init_galaxy, is_initialized, list_worktrees


@click.group()
def main() -> None:
    """galaxy — CAID multi-agent AI orchestrator."""


@main.command()
@click.argument("repo_path", default=".", type=click.Path(exists=True))
def init(repo_path: str) -> None:
    """Initialize galaxy for a repository."""
    path = Path(repo_path).resolve()
    if is_initialized(path):
        click.echo(f"galaxy already initialized at {path}/.galaxy")
        return
    galaxy_dir = init_galaxy(path)
    click.echo(f"Initialized galaxy at {galaxy_dir}")


@main.command()
@click.argument("prompt", required=False)
@click.option("--file", "-f", "task_file", type=click.Path(exists=True),
              help="Read prompt from .md file")
@click.option("--repo", "-r", "repo_path", default=".",
              type=click.Path(exists=True))
@click.option("--agents", "-n", type=int, default=None,
              help="Number of agents (auto-detected if omitted)")
@click.option("--verify", "-v", "verify_cmd", default=None,
              help="Verify command (auto-detected if omitted)")
@click.option("--model", default=None, help="Anthropic model for planning")
def run(
    prompt: str | None,
    task_file: str | None,
    repo_path: str,
    agents: int | None,
    verify_cmd: str | None,
    model: str | None,
) -> None:
    """Run a task with the galaxy swarm."""
    if task_file:
        prompt = Path(task_file).read_text()
    if not prompt:
        raise click.UsageError("Provide PROMPT argument or --file")

    path = Path(repo_path).resolve()
    if not is_initialized(path):
        click.echo("Initializing galaxy...")
        init_galaxy(path)

    config = get_config(path)
    db_path = path / ".galaxy" / "galaxy.db"
    taskbox = Taskbox(db_path)

    planning_model = model or config.get("anthropic_model", "claude-opus-4-7")
    click.echo(f"Planning task with {planning_model}...")

    p = plan_task(prompt, model=planning_model, agent_count_override=agents)
    click.echo(
        f"Complexity: {p.complexity_score}/100 | Agents: {p.agent_count} | Tasks: {len(p.tasks)}"
    )

    vc = verify_cmd or config.get("verify_command") or detect_verify_command(path)
    max_workers = config.get("max_concurrent_workers", 20)
    timeout = config.get("worker_timeout_seconds", 120)

    click.echo(f"Starting swarm (run: {p.run_id})...")
    result = asyncio.run(
        run_manager(
            plan=p, repo_path=path, taskbox=taskbox,
            max_concurrent=max_workers, verify_cmd=vc,
            worker_timeout=timeout,
        )
    )

    click.echo(f"\nRun {result['run_id']}: {result['status'].upper()}")
    click.echo(f"  Completed: {result['completed']}/{result['total']}")
    if result["failed"]:
        click.echo(f"  Failed: {result['failed']}/{result['total']}")


@main.command()
@click.option("--repo", "-r", "repo_path", default=".",
              type=click.Path(exists=True))
@click.option("--run-id", default=None)
def status(repo_path: str, run_id: str | None) -> None:
    """Show status of current or specified run."""
    path = Path(repo_path).resolve()
    if not is_initialized(path):
        click.echo("galaxy not initialized. Run: galaxy init")
        return

    db_path = path / ".galaxy" / "galaxy.db"
    taskbox = Taskbox(db_path)

    if run_id:
        run_rec = taskbox.get_run(run_id)
        if not run_rec:
            click.echo(f"Run {run_id} not found")
            return
        tasks = taskbox.get_tasks(run_id)
        agents = taskbox.get_agents(run_id)
        click.echo(f"Run: {run_rec.id} | Status: {run_rec.status}")
        click.echo(f"Agents: {len(agents)} | Tasks: {len(tasks)}")
        for t in tasks:
            click.echo(f"  [{t.status:12}] {t.id}: {t.description[:60]}")
    else:
        worktrees = list_worktrees(path)
        galaxy_wt = [w for w in worktrees if "galaxy/" in w.get("branch", "")]
        click.echo(f"Active galaxy worktrees: {len(galaxy_wt)}")
        for wt in galaxy_wt:
            click.echo(f"  {wt.get('branch', 'unknown')} -> {wt['path']}")


@main.command()
@click.option("--repo", "-r", "repo_path", default=".",
              type=click.Path(exists=True))
def clean(repo_path: str) -> None:
    """Remove completed galaxy worktrees."""
    import subprocess

    path = Path(repo_path).resolve()
    worktrees = list_worktrees(path)
    galaxy_wt = [w for w in worktrees if "galaxy/" in w.get("branch", "")]

    if not galaxy_wt:
        click.echo("No galaxy worktrees found")
        return

    removed = 0
    for wt in galaxy_wt:
        try:
            subprocess.run(
                ["git", "worktree", "remove", "--force", wt["path"]],
                cwd=path, check=True, capture_output=True,
            )
            removed += 1
        except subprocess.CalledProcessError as exc:
            click.echo(f"  Could not remove {wt['path']}: {exc}")

    click.echo(f"Removed {removed} worktree(s)")
```

- [ ] **Step 4: Run tests to confirm pass**

```bash
pytest tests/test_cli.py -v
```

Expected: `8 passed`

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all tests pass (48+ passed, 0 failed)

- [ ] **Step 6: Commit**

```bash
git add galaxy/cli.py tests/test_cli.py
git commit -m "feat: Click CLI (init/run/status/clean) with TDD"
```

---

## Task 10: README and Final Push

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Write `README.md`**

```markdown
# galaxy

CAID (Centralized Asynchronous Isolated Delegation) multi-agent AI orchestrator.
Fans out coding tasks across N Claude Code workers in isolated git worktrees.

## How It Works

1. `galaxy run "your task"` calls Anthropic API to decompose the task into subtasks
2. Manager assigns each subtask to a Claude Code worker in its own git worktree
3. Workers run concurrently with no file conflicts
4. Completed work is test-gated and merged back to main

## Requirements

- Python 3.11+
- Git
- Claude Code CLI (`npm install -g @anthropic-ai/claude-code`)
- Anthropic API key

## Install

```bash
pip install galaxy-caid
```

Or from source:

```bash
git clone https://github.com/platfrmrcarl/galaxy.git
cd galaxy
pip install -e ".[dev]"
```

## Setup

Set your Anthropic API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

### Initialize galaxy for a repository

```bash
cd /path/to/your/repo
galaxy init
```

Creates `.galaxy/` directory with worktrees, config, and SQLite database.

### Run a task

```bash
# From a prompt (auto-determines agent count)
galaxy run "Build a REST API with JWT auth and user management"

# From a markdown file of tasks
galaxy run --file tasks.md

# Override agent count
galaxy run "Fix the auth bug" --agents 3

# Specify a custom verify command
galaxy run "Add user endpoints" --verify "pytest tests/test_users.py"

# Target a different repo
galaxy run "Build the feature" --repo /path/to/repo
```

### Check status

```bash
# See active worktrees
galaxy status

# See status of a specific run
galaxy status --run-id abc12345
```

### Clean up

```bash
# Remove all finished galaxy worktrees
galaxy clean

# Target a specific repo
galaxy clean --repo /path/to/repo
```

## Agent Count

galaxy auto-determines the number of agents based on task complexity (1–100):

| Complexity | Agents | Example |
|---|---|---|
| 1–20 | 3 | Fix a bug |
| 21–40 | 5–10 | Add a feature |
| 41–60 | 10–20 | Full module + tests |
| 61–80 | 20–50 | Multi-module feature |
| 81–100 | 50–100 | Full project |

Override with `--agents N`.

## Configuration

`.galaxy/config.json` (created by `galaxy init`):

```json
{
  "verify_command": null,
  "default_agent_count": null,
  "worker_timeout_seconds": 120,
  "anthropic_model": "claude-opus-4-7",
  "max_concurrent_workers": 20
}
```

- `verify_command`: override auto-detected test command (`pytest`, `npm test`, `make test`)
- `anthropic_model`: model used for task planning
- `max_concurrent_workers`: max agents running simultaneously (rest queue)
- `worker_timeout_seconds`: kill agent if no output for this many seconds

## Development

```bash
pip install -e ".[dev]"
pytest tests/ -v
```

## Architecture

```
User → CLI → Planner (Anthropic API) → Manager (asyncio)
                                              │
                       ┌──────────┬──────────┤
                       ↓          ↓          ↓
                    Worker 1   Worker 2  ... Worker N
                  (worktree)  (worktree)   (worktree)
                    [claude]   [claude]    [claude]
                       └──────────┴──────────┘
                                  │
                           Taskbox (SQLite)
                                  │
                         Integration Engine
                         (test → merge → notify)
                                  │
                            main branch ✓
```
```

- [ ] **Step 2: Run full test suite one final time**

```bash
pytest tests/ -v --tb=short
```

Expected: all tests pass

- [ ] **Step 3: Verify `galaxy` CLI is available**

```bash
galaxy --help
```

Expected:
```
Usage: galaxy [OPTIONS] COMMAND [ARGS]...

  galaxy — CAID multi-agent AI orchestrator.

Options:
  --help  Show this message and exit.

Commands:
  clean   Remove completed galaxy worktrees.
  init    Initialize galaxy for a repository.
  run     Run a task with the galaxy swarm.
  status  Show status of current or specified run.
```

- [ ] **Step 4: Commit README**

```bash
git add README.md
git commit -m "docs: README with install and operation instructions"
```

- [ ] **Step 5: Push to origin**

```bash
git push origin main
```

Expected: `Branch 'main' set up to track remote branch 'main' from 'origin'.`
