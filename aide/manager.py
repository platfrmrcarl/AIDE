import asyncio
import uuid
from datetime import datetime
from pathlib import Path

from .integration import integrate_worktree
from .models import AgentRecord, Plan, RunRecord
from .taskbox import Taskbox
from .worker import run_worker
from .workspace import create_worktree, symlink_env_files


async def run_manager(
    plan: Plan,
    repo_path: Path,
    taskbox: Taskbox,
    max_concurrent: int = 20,
    verify_cmd: str | None = None,
    worker_cmd: str = "auto",
    worker_timeout: int = 120,
) -> dict:
    taskbox.save_run(
        RunRecord(
            id=plan.run_id,
            prompt=plan.original_prompt,
            agent_count=plan.agent_count,
            complexity_score=plan.complexity_score,
        )
    )
    for task in plan.tasks:
        taskbox.save_task(task, plan.run_id)

    all_ids = {t.id for t in plan.tasks}
    completed: set[str] = set()
    failed: set[str] = set()
    in_flight: dict[str, asyncio.Task] = {}  # task_id -> asyncio.Task
    task_to_agent: dict[str, str] = {}
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _dispatch(subtask) -> None:
        agent_id = f"agent-{str(uuid.uuid4())[:6]}"
        worktree_path, branch = create_worktree(repo_path, plan.run_id, agent_id)
        symlink_env_files(worktree_path, repo_path)

        taskbox.save_agent(
            AgentRecord(
                id=agent_id, run_id=plan.run_id,
                worktree_path=str(worktree_path), branch=branch,
                task_id=subtask.id, last_heartbeat=datetime.utcnow(),
            )
        )
        taskbox.update_task_status(
            subtask.id, "in_progress",
            assigned_agent=agent_id,
            worktree_path=str(worktree_path),
            branch=branch,
        )
        task_to_agent[subtask.id] = agent_id

        async with semaphore:
            await run_worker(
                agent_id=agent_id, run_id=plan.run_id,
                task_id=subtask.id, task_description=subtask.description,
                worktree_path=worktree_path, taskbox=taskbox,
                timeout=worker_timeout, worker_cmd=worker_cmd,
            )

    while len(completed) + len(failed) < len(all_ids):
        # Dispatch all newly unblocked tasks
        dispatchable = [
            t for t in plan.tasks
            if t.id not in completed
            and t.id not in failed
            and t.id not in task_to_agent
            and all(dep in completed for dep in t.depends_on)
        ]
        for subtask in dispatchable:
            in_flight[subtask.id] = asyncio.create_task(_dispatch(subtask))

        # Process messages
        for msg in taskbox.get_unprocessed_messages("manager"):
            taskbox.mark_message_processed(msg.id)
            task_id = msg.payload.get("task_id")
            if not task_id:
                continue

            if msg.type == "COMPLETE":
                agent_id = task_to_agent.get(task_id)
                agents = taskbox.get_agents(plan.run_id)
                agent_rec = next((a for a in agents if a.id == agent_id), None)
                if agent_rec:
                    ok, out = integrate_worktree(
                        repo_path, Path(agent_rec.worktree_path),
                        agent_rec.branch, verify_cmd,
                    )
                    if ok:
                        completed.add(task_id)
                        taskbox.update_task_status(task_id, "complete")
                    else:
                        failed.add(task_id)
                        taskbox.update_task_status(task_id, "failed")
                else:
                    failed.add(task_id)
                    taskbox.update_task_status(task_id, "failed")
                in_flight.pop(task_id, None)

            elif msg.type == "ERROR":
                if task_id:
                    failed.add(task_id)
                    taskbox.update_task_status(task_id, "failed")
                    in_flight.pop(task_id, None)

        # Propagate failures to blocked dependents
        for task in plan.tasks:
            if (
                task.id not in completed
                and task.id not in failed
                and task.id not in task_to_agent
                and any(dep in failed for dep in task.depends_on)
            ):
                failed.add(task.id)
                taskbox.update_task_status(task.id, "failed")

        remaining = all_ids - completed - failed
        if not remaining:
            break

        newly_dispatchable = any(
            t.id not in completed
            and t.id not in failed
            and t.id not in task_to_agent
            and all(dep in completed for dep in t.depends_on)
            for t in plan.tasks
        )
        if in_flight or newly_dispatchable:
            await asyncio.sleep(0.05)
        else:
            break

    status = "complete" if not failed else "failed"
    taskbox.save_run(
        RunRecord(
            id=plan.run_id,
            prompt=plan.original_prompt,
            agent_count=plan.agent_count,
            complexity_score=plan.complexity_score,
            status=status,
            completed_at=datetime.utcnow(),
        )
    )

    return {
        "run_id": plan.run_id,
        "status": status,
        "completed": len(completed),
        "failed": len(failed),
        "total": len(all_ids),
    }
