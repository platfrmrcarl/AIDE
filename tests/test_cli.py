from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from aide.cli import main
from aide.models import Plan, RunRecord, SubTask
from aide.taskbox import Taskbox
from aide.workspace import init_aide


def test_init_creates_aide_dir(runner, git_repo):
    """aide init creates .aide/ directory"""
    result = runner.invoke(main, ["init", str(git_repo)])
    assert result.exit_code == 0
    assert (git_repo / ".aide").exists()
    assert "initialized" in result.output


def test_init_already_initialized(runner, git_repo):
    """aide init on already-initialized repo prints 'already initialized'"""
    init_aide(git_repo)
    result = runner.invoke(main, ["init", str(git_repo)])
    assert result.exit_code == 0
    assert "already initialized" in result.output


def test_run_requires_prompt_or_file(runner, git_repo):
    """aide run with no args exits 1 with error message"""
    init_aide(git_repo)
    result = runner.invoke(main, ["run", "--repo", str(git_repo)])
    assert result.exit_code == 1
    assert "prompt" in result.output.lower() or "file" in result.output.lower()


def test_run_dispatches_plan(runner, git_repo, mocker):
    """aide run calls plan_task and run_manager"""
    init_aide(git_repo)

    fake_plan = Plan(
        run_id="r1",
        original_prompt="do a thing",
        agent_count=1,
        complexity_score=5,
        tasks=[SubTask(id="t1", description="do a thing", depends_on=[])],
    )
    fake_result = {
        "run_id": "r1",
        "status": "complete",
        "completed": 1,
        "failed": 0,
        "total": 1,
    }

    mock_plan = mocker.patch("aide.cli.plan_task", return_value=fake_plan)
    mock_manager = mocker.patch(
        "aide.cli.run_manager",
        new=AsyncMock(return_value=fake_result),
    )

    result = runner.invoke(
        main,
        ["run", "do a thing", "--repo", str(git_repo)],
    )

    assert result.exit_code == 0, result.output
    mock_plan.assert_called_once()
    mock_manager.assert_called_once()
    assert "r1" in result.output
    assert "complete" in result.output


def test_status_no_runs(runner, git_repo):
    """aide status with no runs prints 'No runs found.'"""
    init_aide(git_repo)
    result = runner.invoke(main, ["status", "--repo", str(git_repo)])
    assert result.exit_code == 0
    assert "No runs found" in result.output


def test_status_shows_run(runner, git_repo):
    """aide status shows run info after a run is saved"""
    init_aide(git_repo)
    taskbox = Taskbox(git_repo / ".aide" / "aide.db")
    run = RunRecord(
        id="abc123",
        prompt="test prompt",
        agent_count=3,
        complexity_score=10,
        status="complete",
        started_at=datetime(2024, 1, 1, 12, 0, 0),
        completed_at=datetime(2024, 1, 1, 12, 5, 0),
    )
    taskbox.save_run(run)

    result = runner.invoke(main, ["status", "--repo", str(git_repo)])
    assert result.exit_code == 0
    assert "abc123" in result.output


def test_clean_removes_worktrees(runner, git_repo, mocker):
    """aide clean calls delete_worktree for each listed worktree"""
    init_aide(git_repo)

    fake_worktrees = [
        {"path": "/tmp/wt1", "branch": "aide/r1/agent-1"},
        {"path": "/tmp/wt2", "branch": "aide/r1/agent-2"},
    ]

    mocker.patch("aide.cli.list_worktrees", return_value=fake_worktrees)
    mock_delete = mocker.patch("aide.cli.delete_worktree")

    result = runner.invoke(main, ["clean", "--repo", str(git_repo)])
    assert result.exit_code == 0
    assert mock_delete.call_count == 2
    assert "Removed 2 worktrees" in result.output
