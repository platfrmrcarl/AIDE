import json
import subprocess
import uuid
from pathlib import Path

_AIDE_DIR = ".aide"


# ── Workspace implementations ─────────────────────────────────────────────────

class GitWorkspace:
    mode = "git"

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path

    def create_slot(self, run_id: str, agent_id: str) -> tuple[Path, str]:
        branch = f"aide/{run_id}/{agent_id}"
        worktree_path = self.repo_path / _AIDE_DIR / "worktrees" / agent_id
        subprocess.run(
            ["git", "worktree", "add", "-b", branch, str(worktree_path)],
            cwd=self.repo_path, check=True, capture_output=True,
        )
        symlink_env_files(worktree_path, self.repo_path)
        return worktree_path, branch

    def integrate(self, working_path: Path, slot_id: str, verify_cmd: str | None) -> tuple[bool, str]:
        from .integration import run_verify, merge_branch
        passed, verify_output = run_verify(working_path, verify_cmd)
        if not passed:
            return False, f"verify failed:\n{verify_output}"
        merged, merge_output = merge_branch(self.repo_path, slot_id)
        if not merged:
            return False, f"merge failed:\n{merge_output}"
        return True, f"integrated {slot_id}\n{verify_output}\n{merge_output}"

    def cleanup_slot(self, working_path: Path, slot_id: str) -> None:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(working_path)],
            cwd=self.repo_path, check=True, capture_output=True,
        )

    def list_slots(self) -> list[dict]:
        result = subprocess.run(
            ["git", "worktree", "list", "--porcelain"],
            cwd=self.repo_path, check=True, capture_output=True, text=True,
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


class BareWorkspace:
    mode = "bare"

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    def create_slot(self, run_id: str, agent_id: str) -> tuple[Path, str]:
        slot_id = str(uuid.uuid4())[:8]
        slot_path = self.base_dir / run_id / agent_id
        slot_path.mkdir(parents=True, exist_ok=True)
        return slot_path, slot_id

    def integrate(self, working_path: Path, slot_id: str, verify_cmd: str | None) -> tuple[bool, str]:
        if verify_cmd:
            from .integration import run_verify
            passed, output = run_verify(working_path, verify_cmd)
            if not passed:
                return False, f"verify failed:\n{output}"
        return True, f"output at {working_path}"

    def cleanup_slot(self, working_path: Path, slot_id: str) -> None:
        pass  # aide clean handles explicit deletion via shutil.rmtree

    def list_slots(self) -> list[dict]:
        if not self.base_dir.exists():
            return []
        return [
            {"path": str(p), "slot_id": p.name}
            for p in self.base_dir.iterdir()
            if p.is_dir()
        ]


# ── Factory ───────────────────────────────────────────────────────────────────

def _is_git_repo(path: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=path, capture_output=True,
    )
    return result.returncode == 0


def workspace_factory(
    config: dict,
    repo_path: Path,
    output_dir: Path | None = None,
) -> GitWorkspace | BareWorkspace:
    mode = config.get("mode", "auto")
    if mode == "auto":
        mode = "git" if _is_git_repo(repo_path) else "bare"
    if mode == "git":
        if not _is_git_repo(repo_path):
            raise ValueError("Not a git repository. Use mode: bare or auto.")
        return GitWorkspace(repo_path)
    base = output_dir or (repo_path / _AIDE_DIR / "runs")
    return BareWorkspace(base)


# ── Module-level helpers (preserved for backwards compatibility) ──────────────

def is_initialized(repo_path: Path) -> bool:
    return (repo_path / _AIDE_DIR).exists()


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
                    "worker_timeout_seconds": 120,
                    "max_concurrent_workers": 20,
                },
                indent=2,
            )
        )
    return aide_dir


def get_config(repo_path: Path) -> dict:
    config_path = repo_path / _AIDE_DIR / "config.json"
    if config_path.exists():
        return json.loads(config_path.read_text())
    return {}


def create_worktree(repo_path: Path, run_id: str, agent_id: str) -> tuple[Path, str]:
    branch = f"aide/{run_id}/{agent_id}"
    worktree_path = repo_path / _AIDE_DIR / "worktrees" / agent_id
    subprocess.run(
        ["git", "worktree", "add", "-b", branch, str(worktree_path)],
        cwd=repo_path, check=True, capture_output=True,
    )
    return worktree_path, branch


def delete_worktree(repo_path: Path, worktree_path: Path) -> None:
    subprocess.run(
        ["git", "worktree", "remove", "--force", str(worktree_path)],
        cwd=repo_path, check=True, capture_output=True,
    )


def list_worktrees(repo_path: Path) -> list[dict]:
    result = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo_path, check=True, capture_output=True, text=True,
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
