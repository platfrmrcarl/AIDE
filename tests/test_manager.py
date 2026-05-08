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


# ---------------------------------------------------------------------------
# Existing tests — fake workers now return True/False (dispatch sends COMPLETE)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_manager_single_task_success(db, git_repo):
    init_aide(git_repo)
    plan = _make_plan()
    mock_ws = _make_mock_workspace(git_repo)

    with patch("aide.manager.workspace_factory", return_value=mock_ws), \
         patch("aide.manager.run_worker", new_callable=AsyncMock, return_value=True):
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
        return True

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
         patch("aide.manager.run_worker", new_callable=AsyncMock, return_value=True):
        result = await run_manager(plan, git_repo, db, verify_cmd="true")

    assert result["status"] == "failed"
    assert result["failed"] == 1


@pytest.mark.asyncio
async def test_manager_run_saved_to_taskbox(db, git_repo):
    init_aide(git_repo)
    plan = _make_plan()
    mock_ws = _make_mock_workspace(git_repo)

    with patch("aide.manager.workspace_factory", return_value=mock_ws), \
         patch("aide.manager.run_worker", new_callable=AsyncMock, return_value=True):
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

    with patch("aide.manager.workspace_factory", return_value=mock_ws), \
         patch("aide.manager.run_worker", new_callable=AsyncMock, return_value=True):
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
         patch("aide.manager.run_worker", new_callable=AsyncMock, return_value=True):
        result = await run_manager(plan, tmp_path, db, mode="bare")

    assert result["status"] == "complete"
    assert result["completed"] == 1
    assert "output_paths" in result
    assert str(slot_path) in result["output_paths"]


# ---------------------------------------------------------------------------
# Variant tests
# ---------------------------------------------------------------------------

from aide.judge import VariantCandidate


def _make_plan_v(tasks=None, run_id="testrun1", variants=1):
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


def _mock_workspace_v(tmp_path, n_slots=10):
    ws = MagicMock()
    ws.mode = "git"
    slot_iter = iter([
        (tmp_path / f"slot{i}", f"aide/run/agent-{i:03d}")
        for i in range(n_slots)
    ])
    ws.create_slot.side_effect = lambda run_id, agent_id: next(slot_iter)
    ws.integrate.return_value = (True, "merged")
    return ws


@pytest.mark.asyncio
async def test_manager_variants_1_backward_compat(db, tmp_path):
    plan = _make_plan_v(variants=1)
    ws = _mock_workspace_v(tmp_path)

    with patch("aide.manager.workspace_factory", return_value=ws), \
         patch("aide.manager.run_worker", new_callable=AsyncMock, return_value=True):
        result = await run_manager(plan, tmp_path, db)

    assert result["status"] == "complete"
    assert result["completed"] == 1
    ws.integrate.assert_called_once()


@pytest.mark.asyncio
async def test_manager_variants_3_all_succeed_judge_called(db, tmp_path):
    plan = _make_plan_v(variants=3)
    ws = _mock_workspace_v(tmp_path, n_slots=3)

    # select_winner returns the first real candidate it receives, so agent_id
    # matches an actual saved AgentRecord and the integration lookup succeeds.
    def _pick_first(task_desc, candidates, workspace, **kwargs):
        return candidates[0]

    with patch("aide.manager.workspace_factory", return_value=ws), \
         patch("aide.manager.run_worker", new_callable=AsyncMock, return_value=True), \
         patch("aide.manager.run_verify", return_value=(True, "")), \
         patch("aide.manager.judge") as mock_judge:
        mock_judge.VariantCandidate = VariantCandidate
        mock_judge.select_winner.side_effect = _pick_first

        result = await run_manager(plan, tmp_path, db)

    assert result["status"] == "complete"
    assert mock_judge.select_winner.called
    ws.integrate.assert_called_once()


@pytest.mark.asyncio
async def test_manager_variants_3_one_succeeds_judge_skipped(db, tmp_path):
    plan = _make_plan_v(variants=3)
    ws = _mock_workspace_v(tmp_path, n_slots=3)

    call_count = 0

    async def fake_worker(**kwargs):
        nonlocal call_count
        call_count += 1
        return call_count == 1  # only first worker succeeds

    with patch("aide.manager.workspace_factory", return_value=ws), \
         patch("aide.manager.run_worker", new_callable=AsyncMock, side_effect=fake_worker), \
         patch("aide.manager.judge") as mock_judge:
        mock_judge.VariantCandidate = VariantCandidate

        result = await run_manager(plan, tmp_path, db)

    assert result["status"] == "complete"
    mock_judge.select_winner.assert_not_called()
    ws.integrate.assert_called_once()


@pytest.mark.asyncio
async def test_manager_variants_3_all_fail(db, tmp_path):
    plan = _make_plan_v(variants=3)
    ws = _mock_workspace_v(tmp_path, n_slots=3)

    with patch("aide.manager.workspace_factory", return_value=ws), \
         patch("aide.manager.run_worker", new_callable=AsyncMock, return_value=False):
        result = await run_manager(plan, tmp_path, db)

    assert result["status"] == "failed"
    assert result["failed"] == 1
    ws.integrate.assert_not_called()


@pytest.mark.asyncio
async def test_manager_variants_3_none_pass_verify_judge_gets_all(db, tmp_path):
    plan = _make_plan_v(variants=3)
    ws = _mock_workspace_v(tmp_path, n_slots=3)

    # select_winner returns the first real candidate so the agent_id lookup works.
    def _pick_first(task_desc, candidates, workspace, **kwargs):
        return candidates[0]

    with patch("aide.manager.workspace_factory", return_value=ws), \
         patch("aide.manager.run_worker", new_callable=AsyncMock, return_value=True), \
         patch("aide.manager.run_verify", return_value=(False, "tests failed")), \
         patch("aide.manager.judge") as mock_judge:
        mock_judge.VariantCandidate = VariantCandidate
        mock_judge.select_winner.side_effect = _pick_first

        result = await run_manager(plan, tmp_path, db)

    assert mock_judge.select_winner.called
    call_candidates = mock_judge.select_winner.call_args[0][1]
    assert len(call_candidates) == 3
