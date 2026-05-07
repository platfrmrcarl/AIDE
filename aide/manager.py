import asyncio
import uuid
from datetime import datetime
from pathlib import Path

from .models import AgentRecord, Plan, RunRecord
from .taskbox import Taskbox
from .worker import run_worker
from .workspace import workspace_factory


async def run_manager(
    plan: Plan,
    repo_path: Path,
    taskbox: Taskbox,
    max_concurrent: int = 20,
    verify_cmd: str | None = None,
    worker_cmd: str = "auto",
    worker_timeout: int = 120,
    mode: str = "auto",
    output_dir: Path | None = None,
) -> dict:
    workspace = workspace_factory({"mode": mode}, repo_path, output_dir)
    worker_mode = workspace.mode

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
    in_flight: dict[str, asyncio.Task] = {}
    task_to_agent: dict[str, str] = {}
    output_paths: list[str] = []
    semaphore = asyncio.Semaphore(max_concurrent)

    async def _dispatch(subtask) -> None:
        agent_id = f"agent-{str(uuid.uuid4())[:6]}"
        slot_path, slot_id = workspace.create_slot(plan.run_id, agent_id)

        taskbox.save_agent(
            AgentRecord(
                id=agent_id, run_id=plan.run_id,
                worktree_path=str(slot_path), branch=slot_id,
                task_id=subtask.id, last_heartbeat=datetime.utcnow(),
            )
        )
        taskbox.update_task_status(
            subtask.id, "in_progress",
            assigned_agent=agent_id,
            worktree_path=str(slot_path),
            branch=slot_id,
        )
        task_to_agent[subtask.id] = agent_id

        async with semaphore:
            await run_worker(
                agent_id=agent_id, run_id=plan.run_id,
                task_id=subtask.id, task_description=subtask.description,
                worktree_path=slot_path, taskbox=taskbox,
                timeout=worker_timeout, worker_cmd=worker_cmd,
                mode=worker_mode,
            )

    while len(completed) + len(failed) < len(all_ids):
        dispatchable = [
            t for t in plan.tasks
            if t.id not in completed
            and t.id not in failed
            and t.id not in task_to_agent
            and all(dep in completed for dep in t.depends_on)
        ]
        for subtask in dispatchable:
            in_flight[subtask.id] = asyncio.create_task(_dispatch(subtask))

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
                    ok, out = workspace.integrate(
                        Path(agent_rec.worktree_path), agent_rec.branch, verify_cmd,
                    )
                    if ok:
                        completed.add(task_id)
                        taskbox.update_task_status(task_id, "complete")
                        if worker_mode == "bare":
                            output_paths.append(agent_rec.worktree_path)
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

    result: dict = {
        "run_id": plan.run_id,
        "status": status,
        "completed": len(completed),
        "failed": len(failed),
        "total": len(all_ids),
    }
    if worker_mode == "bare":
        result["output_paths"] = output_paths
    return result
