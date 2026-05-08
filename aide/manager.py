import asyncio
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import judge
from .integration import run_verify
from .models import AgentRecord, Message, Plan, RunRecord
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
    judge_provider: str = "anthropic",
    judge_model: str | None = None,
    on_task_complete: Callable[[str, str, str], None] | None = None,
    stream_output: bool = False,
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
    # Pre-populate completed so rerun skips already-done tasks
    completed: set[str] = {
        t.id for t in taskbox.get_tasks(plan.run_id) if t.status == "complete"
    }
    failed: set[str] = set()
    in_flight: dict[str, asyncio.Task] = {}
    output_paths: list[str] = []
    result_queue: asyncio.Queue[dict] = asyncio.Queue()
    semaphore = asyncio.Semaphore(max_concurrent)

    subtask_map = {t.id: t for t in plan.tasks}

    def _progress_cb(agent_id: str, line: str) -> None:
        if stream_output:
            print(f"  [{agent_id}] {line}", file=sys.stderr, flush=True)

    async def _dispatch(subtask) -> None:
        try:
            slots: list[tuple[str, Path, str]] = []
            worker_coros = []

            for _ in range(plan.variants):
                agent_id = f"agent-{str(uuid.uuid4())[:6]}"
                slot_path, slot_id = workspace.create_slot(plan.run_id, agent_id)
                taskbox.save_agent(
                    AgentRecord(
                        id=agent_id, run_id=plan.run_id,
                        worktree_path=str(slot_path), branch=slot_id,
                        task_id=subtask.id, last_heartbeat=datetime.utcnow(),
                    )
                )
                slots.append((agent_id, slot_path, slot_id))
                worker_coros.append(
                    run_worker(
                        agent_id=agent_id, run_id=plan.run_id,
                        task_id=subtask.id, task_description=subtask.description,
                        worktree_path=slot_path, taskbox=taskbox,
                        timeout=worker_timeout, worker_cmd=worker_cmd,
                        mode=worker_mode, silent=True,
                        progress_callback=_progress_cb,
                    )
                )

            taskbox.update_task_status(
                subtask.id, "in_progress",
                assigned_agent=slots[0][0],
                worktree_path=str(slots[0][1]),
                branch=slots[0][2],
            )

            async with semaphore:
                results: list[bool] = list(await asyncio.gather(*worker_coros))

            successes = [slots[i] for i, ok in enumerate(results) if ok]

            if not successes:
                await result_queue.put({"type": "ERROR", "task_id": subtask.id,
                                        "description": subtask.description})
                return

            if len(successes) == 1:
                winner_agent, winner_path, winner_branch = successes[0]
            else:
                passing = [
                    (a, p, b) for a, p, b in successes
                    if run_verify(p, verify_cmd)[0]
                ]
                pool = passing if passing else successes
                if len(pool) == 1:
                    winner_agent, winner_path, winner_branch = pool[0]
                else:
                    candidates = [
                        judge.VariantCandidate(agent_id=a, slot_path=p, branch=b)
                        for a, p, b in pool
                    ]
                    w = judge.select_winner(
                        subtask.description, candidates, workspace,
                        provider=judge_provider, model=judge_model,
                    )
                    winner_agent = w.agent_id
                    winner_path = w.slot_path
                    winner_branch = w.branch

            taskbox.update_task_status(
                subtask.id, "in_progress",
                assigned_agent=winner_agent,
                worktree_path=str(winner_path),
                branch=winner_branch,
            )
            await result_queue.put({
                "type": "COMPLETE",
                "task_id": subtask.id,
                "winner_path": str(winner_path),
                "winner_branch": winner_branch,
                "description": subtask.description,
            })

        except Exception as exc:
            await result_queue.put({
                "type": "ERROR",
                "task_id": subtask.id,
                "description": subtask_map.get(subtask.id, subtask).description,
                "error": str(exc),
            })

    while len(completed) + len(failed) < len(all_ids):
        # Dispatch all newly-available tasks
        dispatchable = [
            t for t in plan.tasks
            if t.id not in completed
            and t.id not in failed
            and t.id not in in_flight
            and all(dep in completed for dep in t.depends_on)
        ]
        for subtask in dispatchable:
            in_flight[subtask.id] = asyncio.create_task(_dispatch(subtask))

        # Cascade failures for tasks whose dependencies failed
        for task in plan.tasks:
            if (
                task.id not in completed
                and task.id not in failed
                and task.id not in in_flight
                and any(dep in failed for dep in task.depends_on)
            ):
                failed.add(task.id)
                taskbox.update_task_status(task.id, "failed")

        if len(completed) + len(failed) >= len(all_ids):
            break
        if not in_flight:
            break  # nothing running and nothing dispatchable — deadlock guard

        # Wait for next result — no polling, no sleep
        event = await result_queue.get()
        task_id = event["task_id"]
        desc = event.get("description", "")

        if event["type"] == "COMPLETE":
            winner_path = Path(event["winner_path"])
            winner_branch = event["winner_branch"]
            try:
                ok, _out = workspace.integrate(winner_path, winner_branch, verify_cmd)
            except Exception as exc:
                print(f"integrate error ({task_id}): {exc}", file=sys.stderr)
                ok = False
            if ok:
                completed.add(task_id)
                taskbox.update_task_status(task_id, "complete")
                if worker_mode == "bare":
                    output_paths.append(event["winner_path"])
                if on_task_complete:
                    try:
                        on_task_complete(task_id, "complete", desc)
                    except Exception as exc:
                        print(f"on_task_complete error: {exc}", file=sys.stderr)
            else:
                failed.add(task_id)
                taskbox.update_task_status(task_id, "failed")
                if on_task_complete:
                    try:
                        on_task_complete(task_id, "failed", desc)
                    except Exception as exc:
                        print(f"on_task_complete error: {exc}", file=sys.stderr)

        elif event["type"] == "ERROR":
            failed.add(task_id)
            taskbox.update_task_status(task_id, "failed")
            if on_task_complete:
                try:
                    on_task_complete(task_id, "failed", desc)
                except Exception as exc:
                    print(f"on_task_complete error: {exc}", file=sys.stderr)

        in_flight.pop(task_id, None)

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
