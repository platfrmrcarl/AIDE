# Variant Workers + Judge Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--variants N` to `aide run` — dispatch N workers per task, two-stage judge (test gate → LLM) selects the best, winner merges via existing integration path.

**Architecture:** `_dispatch()` spawns N workers with `asyncio.gather`, all workers run `silent=True` (no self-reporting), `_dispatch` judges survivors and sends one COMPLETE or ERROR to the manager. Manager loop body unchanged. New `aide/judge.py` module owns diff extraction and LLM scoring.

**Tech Stack:** Python 3.11+, asyncio, existing provider abstraction (`aide/providers/`), subprocess for git diff, pytest

---

## File Map

| File | Change |
|------|--------|
| `aide/models.py` | Add `Plan.variants: int = 1` |
| `aide/worker.py` | Add `silent: bool = False` param + `-> bool` return |
| `aide/judge.py` | New: `VariantCandidate`, `_get_diff`, `_build_judge_prompt`, `select_winner` |
| `aide/manager.py` | Refactor `_dispatch` for N-worker path; add `judge_provider`/`judge_model` params; import `run_verify` + `judge` |
| `aide/cli.py` | Add `--variants` option; resolve from config; pass to `run_manager` |
| `aide/workspace.py` | Add `"default_variants": 1` to `init_aide()` config template |
| `tests/test_models.py` | Add `Plan.variants` tests |
| `tests/test_worker.py` | Assert bool return; add silent mode test |
| `tests/test_judge.py` | New file |
| `tests/test_manager.py` | Add variant dispatch tests |
| `tests/test_cli.py` | Add `--variants` flag tests |
| `tests/test_workspace.py` | Assert `default_variants` in config |

---

## Task 1: Plan.variants field

**Files:**
- Modify: `aide/models.py`
- Modify: `tests/test_models.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_models.py`:

```python
def test_plan_variants_default():
    tasks = [SubTask(id="t1", description="task", depends_on=[])]
    plan = Plan(run_id="abc", original_prompt="do stuff", agent_count=3,
                complexity_score=15, tasks=tasks)
    assert plan.variants == 1


def test_plan_variants_custom():
    tasks = [SubTask(id="t1", description="task", depends_on=[])]
    plan = Plan(run_id="abc", original_prompt="do stuff", agent_count=3,
                complexity_score=15, tasks=tasks, variants=3)
    assert plan.variants == 3
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_models.py -v -k "variants"
```

Expected: `TypeError: Plan.__init__() got an unexpected keyword argument 'variants'`

- [ ] **Step 3: Add field to Plan**

In `aide/models.py`, change the `Plan` dataclass:

```python
@dataclass
class Plan:
    run_id: str
    original_prompt: str
    agent_count: int
    complexity_score: int
    tasks: list[SubTask]
    variants: int = 1
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_models.py -v
```

Expected: all pass (including 2 new tests)

- [ ] **Step 5: Commit**

```bash
git add aide/models.py tests/test_models.py
git commit -m "feat: add Plan.variants field (default 1)"
```

---

## Task 2: run_worker returns bool + silent param

**Files:**
- Modify: `aide/worker.py`
- Modify: `tests/test_worker.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_worker.py` (keep all existing tests, add these):

```python
@pytest.mark.asyncio
async def test_worker_returns_true_on_success(db, tmp_path):
    make_agent(db, tmp_path)
    result = await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do the thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, worker_cmd="true",
    )
    assert result is True


@pytest.mark.asyncio
async def test_worker_returns_false_on_failure(db, tmp_path):
    make_agent(db, tmp_path)
    result = await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do the thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, worker_cmd="false",
    )
    assert result is False


@pytest.mark.asyncio
async def test_worker_returns_false_on_timeout(db, tmp_path):
    make_agent(db, tmp_path)
    script = tmp_path / "slow.sh"
    script.write_text("#!/bin/sh\nsleep 100\n")
    script.chmod(script.stat().st_mode | 0o111)
    result = await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do the thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=1, worker_cmd=str(script),
    )
    assert result is False


@pytest.mark.asyncio
async def test_worker_silent_suppresses_routing_messages(db, tmp_path):
    make_agent(db, tmp_path)
    result = await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do the thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, worker_cmd="true", silent=True,
    )
    assert result is True
    messages = db.get_unprocessed_messages("manager")
    assert not any(m.type in ("COMPLETE", "ERROR") for m in messages)


@pytest.mark.asyncio
async def test_worker_not_silent_sends_complete(db, tmp_path):
    make_agent(db, tmp_path)
    await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do the thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, worker_cmd="true", silent=False,
    )
    messages = db.get_unprocessed_messages("manager")
    assert any(m.type == "COMPLETE" for m in messages)
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_worker.py -v -k "returns_true or returns_false or silent"
```

Expected: failures — `run_worker` returns `None`, no `silent` param

- [ ] **Step 3: Update run_worker**

Replace the entire `aide/worker.py` with:

```python
import asyncio
import uuid
from datetime import datetime
from pathlib import Path
from typing import Literal

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
    mode: Literal["git", "bare"] = "git",
    silent: bool = False,
) -> bool:
    """Run one worker subprocess. Returns True on success, False on error/timeout.

    When silent=True, suppresses COMPLETE and ERROR messages to the manager
    (used when _dispatch handles routing for variant runs).
    """
    if mode not in ("git", "bare"):
        raise ValueError(f"Unknown mode {mode!r}. Expected 'git' or 'bare'.")
    cmd = worker_cmd if worker_cmd != "auto" else detect_worker_cmd()
    if cmd is None:
        if not silent:
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
        return False

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
            if not silent:
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
            return False

        if proc.returncode == 0:
            if not silent:
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
            return True
        else:
            stderr = b""
            if proc.stderr:
                stderr = await proc.stderr.read()
            if not silent:
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
            return False

    except Exception as exc:
        if not silent:
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
        return False
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_worker.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add aide/worker.py tests/test_worker.py
git commit -m "feat: run_worker returns bool; add silent param to suppress routing messages"
```

---

## Task 3: judge.py — VariantCandidate and diff extraction

**Files:**
- Create: `aide/judge.py`
- Create: `tests/test_judge.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_judge.py`:

```python
import subprocess
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from aide.judge import VariantCandidate, _get_diff


def _make_git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True)
    (tmp_path / "README.md").write_text("init")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "feature.py").write_text("def f(): return 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "feat: add feature"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def test_variant_candidate_fields(tmp_path):
    c = VariantCandidate(agent_id="a1", slot_path=tmp_path, branch="aide/run/a1")
    assert c.agent_id == "a1"
    assert c.slot_path == tmp_path
    assert c.branch == "aide/run/a1"


def test_get_diff_git_mode(tmp_path):
    slot = _make_git_repo(tmp_path)
    candidate = VariantCandidate(agent_id="a1", slot_path=slot, branch="aide/run/a1")
    mock_ws = MagicMock()
    mock_ws.__class__.__name__ = "GitWorkspace"

    from aide.workspace import GitWorkspace
    with patch("aide.judge.isinstance", side_effect=lambda obj, cls: cls is GitWorkspace):
        diff = _get_diff(candidate, mock_ws)

    assert "feature.py" in diff or "feat: add feature" in diff


def test_get_diff_bare_mode_with_output_md(tmp_path):
    (tmp_path / "OUTPUT.md").write_text("# Result\nSome output here\n")
    candidate = VariantCandidate(agent_id="a1", slot_path=tmp_path, branch="slot1")
    mock_ws = MagicMock()

    from aide.workspace import GitWorkspace
    with patch("aide.judge.isinstance", side_effect=lambda obj, cls: False):
        diff = _get_diff(candidate, mock_ws)

    assert diff == "# Result\nSome output here\n"


def test_get_diff_bare_mode_no_output_md(tmp_path):
    candidate = VariantCandidate(agent_id="a1", slot_path=tmp_path, branch="slot1")
    mock_ws = MagicMock()

    from aide.workspace import GitWorkspace
    with patch("aide.judge.isinstance", side_effect=lambda obj, cls: False):
        diff = _get_diff(candidate, mock_ws)

    assert diff == ""
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_judge.py -v -k "candidate or get_diff"
```

Expected: `ImportError: cannot import name 'VariantCandidate' from 'aide.judge'`

- [ ] **Step 3: Create aide/judge.py with dataclass and _get_diff**

```python
import json
import os
import re
import subprocess
import warnings
from dataclasses import dataclass
from pathlib import Path

from .providers import SUPPORTED_PROVIDERS, get_provider


@dataclass
class VariantCandidate:
    agent_id: str
    slot_path: Path
    branch: str


def _get_diff(candidate: VariantCandidate, workspace) -> str:
    from .workspace import GitWorkspace
    if isinstance(workspace, GitWorkspace):
        result = subprocess.run(
            ["git", "show", "--stat", "--patch", "HEAD"],
            cwd=candidate.slot_path,
            capture_output=True,
            text=True,
        )
        return result.stdout[:8000]
    output_file = candidate.slot_path / "OUTPUT.md"
    return output_file.read_text() if output_file.exists() else ""
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_judge.py -v -k "candidate or get_diff"
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add aide/judge.py tests/test_judge.py
git commit -m "feat: VariantCandidate dataclass and _get_diff (git + bare)"
```

---

## Task 4: judge.py — select_winner

**Files:**
- Modify: `aide/judge.py`
- Modify: `tests/test_judge.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_judge.py`:

```python
from aide.judge import select_winner


def _make_candidates(tmp_path, n=2):
    candidates = []
    for i in range(n):
        p = tmp_path / f"slot{i}"
        p.mkdir()
        (p / "OUTPUT.md").write_text(f"output {i}")
        candidates.append(VariantCandidate(agent_id=f"agent-{i:03d}", slot_path=p, branch=f"b{i}"))
    return candidates


def _mock_provider(winner_id: str):
    mod = MagicMock()
    mod.generate.return_value = f'{{"winner": "{winner_id}"}}'
    return mod


def test_select_winner_returns_correct_candidate(tmp_path):
    candidates = _make_candidates(tmp_path, n=2)
    mock_ws = MagicMock()

    with patch("aide.judge.get_provider", return_value=_mock_provider("agent-001")), \
         patch("aide.judge._get_diff", return_value="diff text"), \
         patch("aide.judge.isinstance", side_effect=lambda obj, cls: False):
        winner = select_winner("Build a feature", candidates, mock_ws)

    assert winner.agent_id == "agent-001"


def test_select_winner_fallback_on_invalid_json(tmp_path):
    candidates = _make_candidates(tmp_path, n=2)
    mock_ws = MagicMock()
    bad_provider = MagicMock()
    bad_provider.generate.return_value = "not json at all"

    with patch("aide.judge.get_provider", return_value=bad_provider), \
         patch("aide.judge._get_diff", return_value="diff"), \
         patch("aide.judge.isinstance", side_effect=lambda obj, cls: False):
        winner = select_winner("Build a feature", candidates, mock_ws)

    assert winner is candidates[0]


def test_select_winner_fallback_on_unknown_agent_id(tmp_path):
    candidates = _make_candidates(tmp_path, n=2)
    mock_ws = MagicMock()

    with patch("aide.judge.get_provider", return_value=_mock_provider("agent-UNKNOWN")), \
         patch("aide.judge._get_diff", return_value="diff"), \
         patch("aide.judge.isinstance", side_effect=lambda obj, cls: False):
        winner = select_winner("Build a feature", candidates, mock_ws)

    assert winner is candidates[0]


def test_select_winner_fallback_on_exception(tmp_path):
    candidates = _make_candidates(tmp_path, n=2)
    mock_ws = MagicMock()
    exc_provider = MagicMock()
    exc_provider.generate.side_effect = RuntimeError("API down")

    with patch("aide.judge.get_provider", return_value=exc_provider), \
         patch("aide.judge._get_diff", return_value="diff"), \
         patch("aide.judge.isinstance", side_effect=lambda obj, cls: False):
        winner = select_winner("Build a feature", candidates, mock_ws)

    assert winner is candidates[0]


def test_select_winner_raises_on_unknown_provider(tmp_path):
    candidates = _make_candidates(tmp_path, n=2)
    mock_ws = MagicMock()
    with pytest.raises(ValueError, match="Unknown provider"):
        select_winner("task", candidates, mock_ws, provider="nonexistent")
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_judge.py -v -k "select_winner"
```

Expected: `ImportError: cannot import name 'select_winner' from 'aide.judge'`

- [ ] **Step 3: Add select_winner to aide/judge.py**

Append to `aide/judge.py` (after the existing code):

```python
def _build_judge_prompt(
    task_description: str,
    candidates: list[VariantCandidate],
    workspace,
) -> str:
    parts = [
        f"Task: {task_description}\n\n"
        "Select the best implementation. Criteria: correctness, clarity, minimal diff size.\n"
    ]
    for c in candidates:
        diff = _get_diff(c, workspace)
        parts.append(f"\n[Candidate {c.agent_id}]\n{diff}\n")
    parts.append('\nRespond ONLY with valid JSON: {"winner": "<agent_id>"}')
    return "".join(parts)


def select_winner(
    task_description: str,
    candidates: list[VariantCandidate],
    workspace,
    provider: str = "anthropic",
    model: str | None = None,
) -> VariantCandidate:
    """Pick the best candidate using an LLM judge. Falls back to candidates[0] on any failure.

    Args (positional, in order):
        task_description: task context for the judge prompt
        candidates: variants to compare (must be non-empty)
        workspace: used for diff extraction (GitWorkspace or BareWorkspace)
    Keyword args:
        provider: provider name from SUPPORTED_PROVIDERS (raises ValueError if unknown)
        model: None → provider's default_model
    """
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unknown provider '{provider}'. Supported: {', '.join(SUPPORTED_PROVIDERS)}"
        )
    meta = SUPPORTED_PROVIDERS[provider]
    resolved_model = model or meta["default_model"]
    api_key = os.environ.get(meta["api_key_env"])
    cli_cmd = meta.get("default_cli_cmd") or "claude"

    prompt = _build_judge_prompt(task_description, candidates, workspace)

    try:
        provider_mod = get_provider(provider)
        raw = provider_mod.generate(
            prompt=prompt,
            model=resolved_model,
            api_key=api_key,
            auth_mode="auto",
            cli_cmd=cli_cmd,
            system_prompt="You are a code quality judge. Select the best implementation.",
        )
        match = re.search(r"\{[^}]*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            winner_id = data.get("winner")
            for c in candidates:
                if c.agent_id == winner_id:
                    return c
    except Exception as exc:
        warnings.warn(f"Judge fallback ({provider}): {exc}")

    return candidates[0]
```

- [ ] **Step 4: Run all judge tests**

```bash
pytest tests/test_judge.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add aide/judge.py tests/test_judge.py
git commit -m "feat: judge.select_winner with LLM scoring and fallback"
```

---

## Task 5: manager.py — variant _dispatch

**Files:**
- Modify: `aide/manager.py`
- Modify: `tests/test_manager.py`

- [ ] **Step 1: Read current test_manager.py**

```bash
cat tests/test_manager.py
```

Note the existing mock patterns — you'll preserve existing tests and add new ones below.

- [ ] **Step 2: Write failing variant tests**

Add to `tests/test_manager.py`:

```python
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aide.judge import VariantCandidate
from aide.manager import run_manager
from aide.models import Plan, SubTask


def _make_plan(tasks=None, run_id="testrun1", variants=1):
    if tasks is None:
        tasks = [SubTask(id="t1", description="Do thing A", depends_on=[])]
    return Plan(
        run_id=run_id,
        original_prompt="do stuff",
        agent_count=len(tasks),
        complexity_score=10,
        tasks=tasks,
        variants=variants,
    )


def _mock_workspace(tmp_path, n_slots=1):
    ws = MagicMock()
    ws.mode = "git"
    calls = iter([
        (tmp_path / f"slot{i}", f"aide/run/agent-{i:03d}")
        for i in range(n_slots * 10)  # more than enough
    ])
    ws.create_slot.side_effect = lambda run_id, agent_id: next(calls)
    ws.integrate.return_value = (True, "merged")
    return ws


@pytest.mark.asyncio
async def test_manager_variants_1_backward_compat(db, tmp_path):
    plan = _make_plan(variants=1)
    ws = _mock_workspace(tmp_path, n_slots=1)

    with patch("aide.manager.workspace_factory", return_value=ws), \
         patch("aide.manager.run_worker", new_callable=AsyncMock, return_value=True):
        result = await run_manager(plan, tmp_path, db)

    assert result["status"] == "complete"
    assert result["completed"] == 1
    ws.integrate.assert_called_once()


@pytest.mark.asyncio
async def test_manager_variants_3_all_succeed_judge_called(db, tmp_path):
    plan = _make_plan(variants=3)
    ws = _mock_workspace(tmp_path, n_slots=3)

    winner = VariantCandidate(
        agent_id="agent-001",
        slot_path=tmp_path / "slot1",
        branch="aide/run/agent-001",
    )

    with patch("aide.manager.workspace_factory", return_value=ws), \
         patch("aide.manager.run_worker", new_callable=AsyncMock, return_value=True), \
         patch("aide.manager.run_verify", return_value=(True, "")), \
         patch("aide.manager.judge") as mock_judge:
        mock_judge.VariantCandidate = VariantCandidate
        mock_judge.select_winner.return_value = winner

        result = await run_manager(plan, tmp_path, db)

    assert result["status"] == "complete"
    assert mock_judge.select_winner.called
    ws.integrate.assert_called_once()


@pytest.mark.asyncio
async def test_manager_variants_3_one_succeeds_judge_skipped(db, tmp_path):
    plan = _make_plan(variants=3)
    ws = _mock_workspace(tmp_path, n_slots=3)

    results_iter = iter([True, False, False])

    with patch("aide.manager.workspace_factory", return_value=ws), \
         patch("aide.manager.run_worker", new_callable=AsyncMock,
               side_effect=lambda **kw: results_iter.__next__()), \
         patch("aide.manager.judge") as mock_judge:
        mock_judge.VariantCandidate = VariantCandidate

        result = await run_manager(plan, tmp_path, db)

    assert result["status"] == "complete"
    mock_judge.select_winner.assert_not_called()
    ws.integrate.assert_called_once()


@pytest.mark.asyncio
async def test_manager_variants_3_all_fail(db, tmp_path):
    plan = _make_plan(variants=3)
    ws = _mock_workspace(tmp_path, n_slots=3)

    with patch("aide.manager.workspace_factory", return_value=ws), \
         patch("aide.manager.run_worker", new_callable=AsyncMock, return_value=False):
        result = await run_manager(plan, tmp_path, db)

    assert result["status"] == "failed"
    assert result["failed"] == 1
    ws.integrate.assert_not_called()


@pytest.mark.asyncio
async def test_manager_variants_3_none_pass_verify_judge_gets_all(db, tmp_path):
    plan = _make_plan(variants=3)
    ws = _mock_workspace(tmp_path, n_slots=3)

    winner = VariantCandidate(
        agent_id="agent-000",
        slot_path=tmp_path / "slot0",
        branch="aide/run/agent-000",
    )

    with patch("aide.manager.workspace_factory", return_value=ws), \
         patch("aide.manager.run_worker", new_callable=AsyncMock, return_value=True), \
         patch("aide.manager.run_verify", return_value=(False, "tests failed")), \
         patch("aide.manager.judge") as mock_judge:
        mock_judge.VariantCandidate = VariantCandidate
        mock_judge.select_winner.return_value = winner

        result = await run_manager(plan, tmp_path, db)

    # judge called with all 3 (none passed verify, fallback pool = all successes)
    assert mock_judge.select_winner.called
    call_candidates = mock_judge.select_winner.call_args[0][1]
    assert len(call_candidates) == 3
```

- [ ] **Step 3: Run to confirm failure**

```bash
pytest tests/test_manager.py -v -k "variants"
```

Expected: failures — `run_manager` doesn't accept `variants` in plan yet

- [ ] **Step 4: Rewrite aide/manager.py**

```python
import asyncio
import uuid
from datetime import datetime
from pathlib import Path

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
                )
            )

        # Set tentative tracking before gather so manager loop can find agent_rec
        first_agent, first_path, first_branch = slots[0]
        task_to_agent[subtask.id] = first_agent
        taskbox.update_task_status(
            subtask.id, "in_progress",
            assigned_agent=first_agent,
            worktree_path=str(first_path),
            branch=first_branch,
        )

        async with semaphore:
            results: list[bool] = list(await asyncio.gather(*worker_coros))

        successes = [slots[i] for i, ok in enumerate(results) if ok]

        if not successes:
            taskbox.send_message(
                Message(
                    id=str(uuid.uuid4()), type="ERROR",
                    from_agent=first_agent, to_agent="manager",
                    payload={"task_id": subtask.id, "error": "all variants failed"},
                    created_at=datetime.utcnow(),
                )
            )
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

        # Update tracking to winner before sending COMPLETE
        task_to_agent[subtask.id] = winner_agent
        taskbox.update_task_status(
            subtask.id, "in_progress",
            assigned_agent=winner_agent,
            worktree_path=str(winner_path),
            branch=winner_branch,
        )
        taskbox.send_message(
            Message(
                id=str(uuid.uuid4()), type="COMPLETE",
                from_agent=winner_agent, to_agent="manager",
                payload={"task_id": subtask.id},
                created_at=datetime.utcnow(),
            )
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

- [ ] **Step 5: Run all manager tests**

```bash
pytest tests/test_manager.py -v
```

Expected: all pass (existing + new variant tests)

- [ ] **Step 6: Commit**

```bash
git add aide/manager.py tests/test_manager.py
git commit -m "feat: manager _dispatch spawns N variant workers, judges survivors, merges winner"
```

---

## Task 6: CLI --variants flag

**Files:**
- Modify: `aide/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_cli.py`:

```python
def test_run_variants_flag_passed_to_manager(runner, git_repo):
    with patch("aide.cli.plan_task", return_value=_simple_plan()) as mock_plan, \
         patch("aide.cli.run_manager", new_callable=AsyncMock,
               return_value={"run_id": "abc123", "status": "complete",
                             "completed": 1, "failed": 0, "total": 1}) as mock_mgr:
        runner.invoke(main, [
            "run", "do stuff", "--repo", str(git_repo), "--variants", "3",
        ])

    call_kwargs = mock_mgr.call_args[1]
    # variants ends up in plan.variants, not as direct kwarg
    plan_arg = mock_mgr.call_args[0][0]
    assert plan_arg.variants == 3


def test_run_variants_defaults_to_1(runner, git_repo):
    with patch("aide.cli.plan_task", return_value=_simple_plan()), \
         patch("aide.cli.run_manager", new_callable=AsyncMock,
               return_value={"run_id": "abc123", "status": "complete",
                             "completed": 1, "failed": 0, "total": 1}) as mock_mgr:
        runner.invoke(main, ["run", "do stuff", "--repo", str(git_repo)])

    plan_arg = mock_mgr.call_args[0][0]
    assert plan_arg.variants == 1
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_cli.py -v -k "variants"
```

Expected: failures — no `--variants` option on `run` command

- [ ] **Step 3: Update aide/cli.py run command**

In the `run` command, add the `--variants` option and thread it into the plan:

```python
@main.command()
@click.argument("prompt", required=False)
@click.option("--file", "-f", "task_file", type=click.Path(exists=True))
@click.option("--repo", default=".", type=click.Path())
@click.option("--agents", type=int, default=None)
@click.option("--verify", "verify_cmd", default=None)
@click.option("--variants", type=int, default=None,
              help="Workers per task for variant selection (default: 1)")
@click.option("--output", "output_dir", default=None, type=click.Path(),
              help="Output directory for bare mode agent results.")
def run(prompt, task_file, repo, agents, verify_cmd, variants, output_dir):
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

    # Resolve variants: CLI flag → config → 1
    resolved_variants = variants if variants is not None else config.get("default_variants", 1)
    plan.variants = resolved_variants

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
            judge_provider=config.get("provider", "anthropic"),
            judge_model=config.get("model"),
        )
    )

    click.echo(
        f"Run {result['run_id']}: {result['status']} "
        f"({result['completed']}/{result['total']} tasks)"
    )
    for path in result.get("output_paths", []):
        click.echo(f"  → {path}")
```

- [ ] **Step 4: Run all CLI tests**

```bash
pytest tests/test_cli.py -v
```

Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add aide/cli.py tests/test_cli.py
git commit -m "feat: add --variants flag to aide run; resolve from config with default 1"
```

---

## Task 7: workspace.py config template

**Files:**
- Modify: `aide/workspace.py`
- Modify: `tests/test_workspace.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_workspace.py`:

```python
def test_init_aide_config_includes_default_variants(git_repo):
    init_aide(git_repo)
    config = get_config(git_repo)
    assert "default_variants" in config
    assert config["default_variants"] == 1
```

- [ ] **Step 2: Run to confirm failure**

```bash
pytest tests/test_workspace.py -v -k "default_variants"
```

Expected: `AssertionError: assert 'default_variants' in {...}`

- [ ] **Step 3: Update init_aide config template**

In `aide/workspace.py`, find the `init_aide` function. Update the `config_path.write_text` call to include `"default_variants"`:

```python
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
                    "default_variants": 1,
                    "worker_timeout_seconds": 120,
                    "max_concurrent_workers": 20,
                },
                indent=2,
            )
        )
    return aide_dir
```

- [ ] **Step 4: Run all workspace tests**

```bash
pytest tests/test_workspace.py -v
```

Expected: all pass

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all pass (0 failures)

- [ ] **Step 6: Commit**

```bash
git add aide/workspace.py tests/test_workspace.py
git commit -m "feat: add default_variants:1 to aide init config template"
```

---

## Self-Review

**Spec coverage check:**

| Spec requirement | Task |
|---|---|
| `--variants N` CLI flag | Task 6 |
| `Plan.variants` field | Task 1 |
| N workers dispatched per task | Task 5 (`_dispatch` loop) |
| `run_worker` returns bool | Task 2 |
| `silent=True` suppresses routing messages | Task 2 |
| Test gate (run_verify each) | Task 5 |
| Judge among survivors | Task 4 + Task 5 |
| Fallback: judge all if none pass verify | Task 5 (`pool = passing if passing else successes`) |
| Fallback: skip judge if 1 success | Task 5 |
| `candidates[0]` fallback on bad JSON | Task 4 |
| `candidates[0]` fallback on unknown agent_id | Task 4 |
| `candidates[0]` fallback on exception | Task 4 |
| Git diff extraction | Task 3 |
| Bare OUTPUT.md extraction | Task 3 |
| `default_variants` in config template | Task 7 |
| Config resolution order (CLI → config → 1) | Task 6 |
| Manager loop body unchanged | Task 5 (loop body preserved verbatim) |
| `judge_provider`/`judge_model` params on `run_manager` | Task 5 |
| Unknown provider raises ValueError | Task 4 |
| `model=None` → provider default | Task 4 (`resolved_model = model or meta["default_model"]`) |
| Semaphore acquires once per task (not per worker) | Task 5 (single `async with semaphore` wraps gather) |

All requirements covered. No gaps found.
