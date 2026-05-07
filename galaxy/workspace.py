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
