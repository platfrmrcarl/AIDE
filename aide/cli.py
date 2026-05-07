import asyncio
from pathlib import Path

import click

from .manager import run_manager
from .planner import plan_task
from .taskbox import Taskbox
from .workspace import (
    delete_worktree,
    get_config,
    init_aide,
    is_initialized,
    list_worktrees,
)


@click.group()
def main():
    pass


@main.command()
@click.argument("repo_path", default=".", type=click.Path())
def init(repo_path):
    """Initialize AIDE for a git repository."""
    path = Path(repo_path).resolve()
    if is_initialized(path):
        click.echo(f"AIDE already initialized at {path}")
        return
    init_aide(path)
    click.echo(f"AIDE initialized at {path}")


@main.command()
@click.argument("prompt", required=False)
@click.option("--file", "-f", "task_file", type=click.Path(exists=True))
@click.option("--repo", default=".", type=click.Path())
@click.option("--agents", type=int, default=None)
@click.option("--verify", "verify_cmd", default=None)
def run(prompt, task_file, repo, agents, verify_cmd):
    """Run agents on a task prompt or .md file."""
    # Validate: require prompt or file, not both, not neither
    if prompt and task_file:
        click.echo("Error: provide either a prompt or --file, not both.")
        raise SystemExit(1)
    if not prompt and not task_file:
        click.echo("Error: provide a prompt or --file.")
        raise SystemExit(1)

    repo_path = Path(repo).resolve()

    if not is_initialized(repo_path):
        click.echo(f"Error: AIDE is not initialized at {repo_path}. Run 'aide init' first.")
        raise SystemExit(1)

    if task_file:
        prompt = Path(task_file).read_text()

    config = get_config(repo_path)
    plan = plan_task(
        prompt,
        model=config.get("anthropic_model", "claude-opus-4-7"),
        agent_count_override=agents,
        auth_mode=config.get("auth_mode", "auto"),
        claude_cmd=config.get("claude_cmd", "claude"),
    )

    taskbox = Taskbox(repo_path / ".aide" / "aide.db")

    result = asyncio.run(
        run_manager(
            plan,
            repo_path,
            taskbox,
            max_concurrent=config.get("max_concurrent_workers", 20),
            verify_cmd=verify_cmd or config.get("verify_command"),
            claude_cmd="claude",
            worker_timeout=config.get("worker_timeout_seconds", 120),
        )
    )

    click.echo(
        f"Run {result['run_id']}: {result['status']} "
        f"({result['completed']}/{result['total']} tasks)"
    )


@main.command()
@click.option("--repo", default=".", type=click.Path())
@click.option("--run-id", default=None)
def status(repo, run_id):
    """Show status of runs."""
    repo_path = Path(repo).resolve()
    taskbox = Taskbox(repo_path / ".aide" / "aide.db")

    if run_id:
        run = taskbox.get_run(run_id)
        if not run:
            click.echo(f"Run {run_id} not found.")
            return
        completed_at = run.completed_at.isoformat() if run.completed_at else "running"
        click.echo(f"{run.id}: {run.status} ({completed_at})")
        tasks = taskbox.get_tasks(run_id)
        for task in tasks:
            click.echo(f"  {task.id}: {task.status} — {task.description}")
    else:
        runs = taskbox.list_runs()
        if not runs:
            click.echo("No runs found.")
            return
        for run in runs[:5]:
            completed_at = run.completed_at.isoformat() if run.completed_at else "running"
            click.echo(f"{run.id}: {run.status} ({completed_at})")


@main.command()
@click.option("--repo", default=".", type=click.Path())
@click.option("--all", "all_worktrees", is_flag=True, default=False)
def clean(repo, all_worktrees):
    """Remove finished worktrees."""
    repo_path = Path(repo).resolve()
    worktrees = list_worktrees(repo_path)
    count = 0
    for wt in worktrees:
        wt_path = Path(wt["path"])
        delete_worktree(repo_path, wt_path)
        count += 1
    click.echo(f"Removed {count} worktrees.")
