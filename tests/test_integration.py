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
    for candidate in ("main", "master"):
        r = subprocess.run(["git", "checkout", candidate], cwd=git_repo,
                           capture_output=True)
        if r.returncode == 0:
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
