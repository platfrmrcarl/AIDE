import asyncio
import json
import shutil
from pathlib import Path

import click

from .manager import run_manager
from .planner import plan_task
from .providers import SUPPORTED_PROVIDERS, detect_worker_cmd
from .taskbox import Taskbox
from .workspace import (
    BareWorkspace,
    get_config,
    init_aide,
    is_initialized,
    workspace_factory,
)


@click.group()
def main():
    pass


@main.command()
@click.argument("repo_path", default=".", type=click.Path())
@click.option("--no-interactive", is_flag=True, default=False,
              help="Skip prompts and use defaults.")
def init(repo_path, no_interactive):
    """Initialize AIDE in a directory (git repo not required)."""
    path = Path(repo_path).resolve()
    if is_initialized(path):
        click.echo(f"AIDE already initialized at {path}")
        return

    if no_interactive:
        init_aide(path)
        click.echo(f"AIDE initialized at {path}")
        return

    # Interactive setup
    provider = click.prompt(
        "Provider",
        type=click.Choice(list(SUPPORTED_PROVIDERS.keys())),
        default="anthropic",
    )
    meta = SUPPORTED_PROVIDERS[provider]
    model = click.prompt("Model", default=meta["default_model"])
    auth_choices = (
        ["auto", "api_key", "subscription"]
        if meta["supports_subscription"]
        else ["auto", "api_key"]
    )
    auth_mode = click.prompt(
        "Auth mode",
        type=click.Choice(auth_choices),
        default="auto",
    )
    api_key_env = click.prompt("API key env var", default=meta["api_key_env"])
    mode = click.prompt(
        "Workspace mode",
        type=click.Choice(["auto", "git", "bare"]),
        default="auto",
    )

    detected_cli = detect_worker_cmd()
    if detected_cli:
        click.echo(f"Detected worker CLI: {detected_cli} ✓")
    else:
        click.echo("Warning: No worker CLI found (claude/codex/gemini). Install one before running.")

    init_aide(path)

    config_path = path / ".aide" / "config.json"
    existing = json.loads(config_path.read_text())
    existing.update({
        "mode": mode,
        "provider": provider,
        "model": model,
        "auth_mode": auth_mode,
        "api_key_env": api_key_env,
    })
    config_path.write_text(json.dumps(existing, indent=2))

    click.echo(f"AIDE initialized at {path}")


@main.command()
@click.argument("prompt", required=False)
@click.option("--file", "-f", "task_file", type=click.Path(exists=True))
@click.option("--repo", default=".", type=click.Path())
@click.option("--agents", type=int, default=None)
@click.option("--verify", "verify_cmd", default=None)
@click.option("--output", "output_dir", default=None, type=click.Path(),
              help="Output directory for bare mode agent results.")
@click.option("--variants", type=int, default=None,
              help="Workers per task for variant selection (default: 1)")
def run(prompt, task_file, repo, agents, verify_cmd, output_dir, variants):
    """Run agents on a task prompt or .md file."""
    if prompt and task_file:
        click.echo("Error: provide either a prompt or --file, not both.")
        raise SystemExit(1)
    if not prompt and not task_file:
        click.echo("Error: provide a prompt or --file.", err=True)
        raise SystemExit(1)

    repo_path = Path(repo).resolve()

    if not is_initialized(repo_path):
        init_aide(repo_path)

    if task_file:
        prompt = Path(task_file).read_text()

    config = get_config(repo_path)

    plan = plan_task(
        prompt,
        provider=config.get("provider", "anthropic"),
        model=config.get("model"),
        auth_mode=config.get("auth_mode", "auto"),
        api_key_env=config.get("api_key_env"),
        agent_count_override=agents,
    )

    # Resolve variants: CLI flag → config → 1
    resolved_variants = variants if variants is not None else config.get("default_variants", 1)
    plan.variants = resolved_variants

    taskbox = Taskbox(repo_path / ".aide" / "aide.db")

    result = asyncio.run(
        run_manager(
            plan,
            repo_path,
            taskbox,
            max_concurrent=config.get("max_concurrent_workers", 20),
            verify_cmd=verify_cmd or config.get("verify_command"),
            worker_cmd=config.get("worker_cmd", "auto"),
            worker_timeout=config.get("worker_timeout_seconds", 120),
            mode=config.get("mode", "auto"),
            output_dir=Path(output_dir) if output_dir else None,
            judge_provider=config.get("provider", "anthropic"),
            judge_model=config.get("model"),
        )
    )

    click.echo(
        f"Run {result['run_id']}: {result['status']} "
        f"({result['completed']}/{result['total']} tasks)"
    )
    for path in result.get("output_paths", []):
        click.echo(f"  → {path}")


@main.command()
@click.option("--repo", default=".", type=click.Path())
@click.option("--run-id", default=None)
def status(repo, run_id):
    """Show status of runs."""
    repo_path = Path(repo).resolve()
    taskbox = Taskbox(repo_path / ".aide" / "aide.db")

    if run_id:
        run_rec = taskbox.get_run(run_id)
        if not run_rec:
            click.echo(f"Run {run_id} not found.")
            return
        completed_at = run_rec.completed_at.isoformat() if run_rec.completed_at else "running"
        click.echo(f"{run_rec.id}: {run_rec.status} ({completed_at})")
        tasks = taskbox.get_tasks(run_id)
        for task in tasks:
            click.echo(f"  {task.id}: {task.status} — {task.description}")
    else:
        runs = taskbox.list_runs()
        if not runs:
            click.echo("No runs found.")
            return
        for run_rec in runs[:5]:
            completed_at = run_rec.completed_at.isoformat() if run_rec.completed_at else "running"
            click.echo(f"{run_rec.id}: {run_rec.status} ({completed_at})")


@main.command()
@click.option("--repo", default=".", type=click.Path())
def clean(repo):
    """Remove finished agent workspaces."""
    repo_path = Path(repo).resolve()
    config = get_config(repo_path) if is_initialized(repo_path) else {}
    ws = workspace_factory(config, repo_path)
    slots = ws.list_slots()
    count = 0
    for slot in slots:
        slot_path = Path(slot["path"])
        if isinstance(ws, BareWorkspace):
            shutil.rmtree(slot_path, ignore_errors=True)
        else:
            ws.cleanup_slot(slot_path, slot.get("branch", slot.get("slot_id", "")))
        count += 1
    click.echo(f"Removed {count} worktrees.")
