from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aide.cli import main
from aide.models import Plan, RunRecord, SubTask
from aide.taskbox import Taskbox
from aide.workspace import init_aide


def test_init_creates_aide_dir(runner, git_repo):
    """aide init creates .aide/ directory"""
    result = runner.invoke(main, ["init", str(git_repo), "--no-interactive"])
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


def test_init_no_interactive_uses_defaults(runner, git_repo):
    """aide init --no-interactive writes default config without prompting."""
    result = runner.invoke(main, ["init", str(git_repo), "--no-interactive"])
    assert result.exit_code == 0
    config_path = git_repo / ".aide" / "config.json"
    assert config_path.exists()
    import json
    config = json.loads(config_path.read_text())
    assert config["provider"] == "anthropic"
    assert config["auth_mode"] == "auto"


def test_run_passes_provider_to_plan_task(runner, git_repo, mocker):
    """aide run passes provider/model/auth_mode from config to plan_task."""
    init_aide(git_repo)
    import json
    config_path = git_repo / ".aide" / "config.json"
    config = json.loads(config_path.read_text())
    config["provider"] = "openai"
    config["model"] = "gpt-4o"
    config_path.write_text(json.dumps(config))

    from aide.models import Plan, SubTask
    fake_plan = Plan(
        run_id="r1", original_prompt="do a thing",
        agent_count=1, complexity_score=5,
        tasks=[SubTask(id="t1", description="do a thing", depends_on=[])],
    )
    mock_plan = mocker.patch("aide.cli.plan_task", return_value=fake_plan)
    mocker.patch("aide.cli.run_manager", new=AsyncMock(return_value={
        "run_id": "r1", "status": "complete", "completed": 1, "failed": 0, "total": 1,
    }))

    result = runner.invoke(main, ["run", "do a thing", "--repo", str(git_repo)])
    assert result.exit_code == 0, result.output
    call_kwargs = mock_plan.call_args
    assert call_kwargs.kwargs.get("provider") == "openai" or (len(call_kwargs.args) > 1 and call_kwargs.args[1] == "openai")


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
