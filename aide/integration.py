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
        ["git", "merge", "--no-ff", branch, "-m", f"aide: merge {branch}"],
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
