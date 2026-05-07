# AIDE Bare Mode (Git-Optional) Design Spec

**Date:** 2026-05-07
**Status:** Approved
**Repo:** platfrmrcarl/AIDE

---

## Overview

Make git optional in AIDE by introducing a `Workspace` protocol with two implementations: `GitWorkspace` (current behavior) and `BareWorkspace` (temp dirs, no git). The manager, worker, and CLI become mode-agnostic. AIDE becomes a general-purpose async DAG task runner for any agentic work — coding in a git repo, content generation, research, data processing, or embedded library use.

---

## Goals

1. `mode: "auto" | "git" | "bare"` config key — auto-detects git at runtime
2. `BareWorkspace` gives each agent a temp directory, no git ops
3. `GitWorkspace` wraps current git worktree behavior, no behavior change
4. Worker picks TASK.md template based on mode — bare template omits git instructions
5. `aide run` works without prior `aide init` (auto-inits silently)
6. `aide run` works outside a git repo
7. Bare mode output persists in slot dirs until `aide clean`
8. Final output lists per-task output paths in bare mode

---

## Non-Goals

- Streaming agent output to the caller in real time
- Remote/cloud workspace backends (S3, Docker)
- Merging bare mode outputs into a single directory automatically
- Python programmatic API (separate effort)

---

## Architecture

```
aide/
  workspace.py     # Workspace protocol, GitWorkspace, BareWorkspace, workspace_factory()
  worker.py        # mode param + two TASK.md templates
  manager.py       # calls workspace_factory(), drops direct git references
  integration.py   # logic moves into GitWorkspace.integrate()
  cli.py           # --output option on run, auto-init, mode prompt in init
```

### Workspace Protocol

```python
class Workspace(Protocol):
    def create_slot(self, run_id: str, agent_id: str) -> tuple[Path, str]:
        """Create isolated working dir. Returns (path, slot_id).
        Git: slot_id = branch name. Bare: slot_id = uuid str."""

    def integrate(self, working_path: Path, slot_id: str, verify_cmd: str | None) -> tuple[bool, str]:
        """Finalize agent work.
        Git: run_verify() + merge_branch(). Bare: optional verify, output preserved."""

    def cleanup_slot(self, working_path: Path, slot_id: str) -> None:
        """Git: git worktree remove. Bare: no-op (aide clean handles deletion)."""

    def list_slots(self) -> list[dict]:
        """Git: git worktree list. Bare: list subdirs of base_dir."""
```

---

## GitWorkspace

Current `workspace.py` + `integration.py` logic extracted into a class. No behavior change.

```python
class GitWorkspace:
    def __init__(self, repo_path: Path): ...

    def create_slot(self, run_id, agent_id) -> tuple[Path, str]:
        # git worktree add -b aide/<run>/<agent> .aide/worktrees/<agent_id>
        # symlink_env_files()
        # returns (worktree_path, branch)

    def integrate(self, working_path, slot_id, verify_cmd) -> tuple[bool, str]:
        # run_verify(working_path, verify_cmd)
        # merge_branch(self.repo_path, slot_id)

    def cleanup_slot(self, working_path, slot_id) -> None:
        # git worktree remove --force working_path

    def list_slots(self) -> list[dict]:
        # git worktree list --porcelain
```

---

## BareWorkspace

New class, no git dependency.

```python
class BareWorkspace:
    def __init__(self, base_dir: Path):
        # base_dir = .aide/runs/ or --output dir

    def create_slot(self, run_id, agent_id) -> tuple[Path, str]:
        # slot_id = str(uuid4())[:8]
        # slot_path = base_dir / run_id / agent_id
        # slot_path.mkdir(parents=True, exist_ok=True)
        # returns (slot_path, slot_id)

    def integrate(self, working_path, slot_id, verify_cmd) -> tuple[bool, str]:
        # if verify_cmd: run it in working_path; fail if non-zero
        # else: always succeed
        # output preserved at working_path
        # returns (True, f"output at {working_path}")

    def cleanup_slot(self, working_path, slot_id) -> None:
        # no-op — aide clean deletes slot dirs explicitly

    def list_slots(self) -> list[dict]:
        # list immediate subdirs of base_dir
        # returns [{"path": str, "slot_id": name}, ...]
```

`BareWorkspace.integrate` never deletes the working directory. Output persists until `aide clean` is called.

---

## workspace_factory

```python
def workspace_factory(config: dict, repo_path: Path, output_dir: Path | None = None) -> Workspace:
    mode = config.get("mode", "auto")
    if mode == "auto":
        mode = "git" if _is_git_repo(repo_path) else "bare"
    if mode == "git":
        return GitWorkspace(repo_path)
    base = output_dir or (repo_path / ".aide" / "runs")
    return BareWorkspace(base)

def _is_git_repo(path: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=path, capture_output=True,
    )
    return result.returncode == 0
```

---

## Worker Changes

`run_worker` gains `mode: str = "git"` parameter. Template selected at call time.

**Git template** (unchanged behavior):
```markdown
# Agent Task

{description}

## Instructions
- Work only within this directory
- Run tests to verify your work
- Commit when done: git add -A && git commit -m "feat: {short_desc}"
- Do NOT push

## Context
- Run ID: {run_id}
- Agent ID: {agent_id}
```

**Bare template** (new):
```markdown
# Agent Task

{description}

## Instructions
- Work only within this directory
- Write any file output to this directory
- If the task produces text (names, copy, analysis), write it to OUTPUT.md
- Do NOT use git

## Context
- Run ID: {run_id}
- Agent ID: {agent_id}
```

Stdout is still streamed to the taskbox as PROGRESS messages in both modes — no change to the subprocess handling.

---

## Manager Changes

`run_manager` gains `mode: str = "auto"` and `output_dir: Path | None = None` params. Calls `workspace_factory(config, repo_path, output_dir)` at start. Replaces direct calls to `create_worktree`, `symlink_env_files`, `integrate_worktree`, `delete_worktree` with workspace method calls.

`_dispatch` inner function passes `mode` to `run_worker`.

Final result dict gains `output_paths` in bare mode:
```python
{
    "run_id": "abc123",
    "status": "complete",
    "completed": 3,
    "failed": 0,
    "total": 3,
    "output_paths": ["/path/.aide/runs/abc123/agent-xyz", ...],  # bare mode only
}
```

---

## Config Changes

New key added to default config written by `init_aide`:

```json
{
  "mode": "auto",
  "provider": "anthropic",
  "model": "claude-opus-4-7",
  "auth_mode": "auto",
  "api_key_env": "ANTHROPIC_API_KEY",
  "worker_cmd": "auto",
  "verify_command": null,
  "default_agent_count": null,
  "worker_timeout_seconds": 120,
  "max_concurrent_workers": 20
}
```

| Value | Behavior |
|-------|----------|
| `"auto"` | Detect at runtime: git repo → `GitWorkspace`, no git repo → `BareWorkspace` |
| `"git"` | Force `GitWorkspace` — error if not in a git repo |
| `"bare"` | Force `BareWorkspace` — skip all git ops |

---

## CLI Changes

### `aide init`

- Works without a git repo — creates `.aide/` in current directory regardless
- Interactive mode gains: `Mode? [auto/git/bare] (auto):`
- `--no-interactive` writes `mode: "auto"` as default

### `aide run`

- New option: `--output DIR` — overrides `BareWorkspace.base_dir`
- No longer requires git repo check before running
- Auto-inits silently if `.aide/` does not exist (writes defaults, no prompts)
- Bare mode final output:
  ```
  Run abc123: complete (3/3 tasks)
    t1 → .aide/runs/abc123/agent-xyz/
    t2 → .aide/runs/abc123/agent-abc/
    t3 → .aide/runs/abc123/agent-def/
  ```

### `aide clean`

- Git mode: `git worktree remove` as before
- Bare mode: `shutil.rmtree` on slot dirs under `.aide/runs/`

---

## Error Handling

| Situation | Behavior |
|-----------|----------|
| `mode: "git"` but not in a git repo | Error at `workspace_factory`: "Not a git repository. Use mode: bare or auto." |
| `mode: "bare"`, verify_cmd set, verify fails | Task marked failed, slot dir preserved for inspection |
| No worker CLI found | Unchanged — ERROR message sent, task marked failed |

---

## Testing

- `test_workspace.py` — add `TestGitWorkspace` (extracts existing tests), `TestBareWorkspace` (create_slot makes dir, integrate returns True with no verify_cmd, cleanup_slot is no-op, list_slots returns dirs)
- `test_worker.py` — add `test_worker_bare_mode_writes_bare_template`
- `test_manager.py` — add bare mode integration test with `BareWorkspace` mock
- `test_cli.py` — add `test_run_auto_inits_if_not_initialized`, `test_run_bare_mode_output_paths`
- Existing tests: pass `GitWorkspace` explicitly — no breakage

---

## Files Modified

| Action | Path |
|--------|------|
| Modify | `aide/workspace.py` — add `GitWorkspace`, `BareWorkspace`, `workspace_factory`, `_is_git_repo` |
| Modify | `aide/worker.py` — add `mode` param, bare TASK.md template |
| Modify | `aide/manager.py` — use `workspace_factory`, pass `mode` to worker |
| Modify | `aide/integration.py` — `run_verify` and `merge_branch` stay as standalone functions, used internally by `GitWorkspace.integrate`; `integrate_worktree` wrapper preserved so existing callers don't break |
| Modify | `aide/cli.py` — `--output` on run, auto-init, mode prompt in init |
| Modify | `tests/test_workspace.py` — add bare workspace tests |
| Modify | `tests/test_worker.py` — add bare template test |
| Modify | `tests/test_manager.py` — add bare mode test |
| Modify | `tests/test_cli.py` — add auto-init + output path tests |
