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
