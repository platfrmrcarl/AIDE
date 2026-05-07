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
