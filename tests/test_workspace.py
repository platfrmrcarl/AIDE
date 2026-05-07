import subprocess
import pytest
from pathlib import Path
from aide.workspace import (
    detect_verify_command,
    create_worktree,
    delete_worktree,
    get_config,
    init_aide,
    is_initialized,
    list_worktrees,
    symlink_env_files,
)


def test_is_initialized_false(git_repo):
    assert not is_initialized(git_repo)


def test_init_aide(git_repo):
    aide_dir = init_aide(git_repo)
    assert is_initialized(git_repo)
    assert (aide_dir / "worktrees").exists()
    assert (aide_dir / "runs").exists()
    assert (aide_dir / "config.json").exists()


def test_init_aide_idempotent(git_repo):
    init_aide(git_repo)
    init_aide(git_repo)
    assert is_initialized(git_repo)


def test_get_config(git_repo):
    init_aide(git_repo)
    config = get_config(git_repo)
    assert "worker_timeout_seconds" in config
    assert config["max_concurrent_workers"] == 20


def test_create_and_delete_worktree(git_repo):
    init_aide(git_repo)
    wt_path, branch = create_worktree(git_repo, "run123", "agent-001")
    assert wt_path.exists()
    assert branch == "aide/run123/agent-001"
    delete_worktree(git_repo, wt_path)
    assert not wt_path.exists()


def test_list_worktrees_includes_aide_branch(git_repo):
    init_aide(git_repo)
    create_worktree(git_repo, "run123", "agent-001")
    worktrees = list_worktrees(git_repo)
    branches = [w.get("branch", "") for w in worktrees]
    assert any("aide/run123/agent-001" in b for b in branches)


def test_symlink_env_files(git_repo):
    init_aide(git_repo)
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


def test_init_aide_config_has_provider_fields(git_repo):
    """New config schema includes provider, model, auth_mode, api_key_env, worker_cmd."""
    init_aide(git_repo)
    config = get_config(git_repo)
    assert config["provider"] == "anthropic"
    assert config["model"] == "claude-opus-4-7"
    assert config["auth_mode"] == "auto"
    assert config["api_key_env"] == "ANTHROPIC_API_KEY"
    assert config["worker_cmd"] == "auto"
    assert "anthropic_model" not in config
    assert "claude_cmd" not in config


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
    ws.create_slot("run2", "agent-def")
    slots = ws.list_slots()
    paths = [s["path"] for s in slots]
    assert len(slots) == 2
    assert any("run1" in p for p in paths)
    assert any("run2" in p for p in paths)
    assert all("slot_id" in s for s in slots)


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


def test_workspace_factory_defaults_to_auto_when_no_mode_key(tmp_path):
    ws = workspace_factory({}, tmp_path)
    assert isinstance(ws, BareWorkspace)


def test_workspace_factory_git_mode_raises_outside_repo(tmp_path):
    with pytest.raises(ValueError, match="Not a git repository"):
        workspace_factory({"mode": "git"}, tmp_path)


def test_init_aide_config_has_mode_field(tmp_path):
    init_aide(tmp_path)
    config = get_config(tmp_path)
    assert config["mode"] == "auto"
