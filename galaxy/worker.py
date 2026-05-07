import asyncio
import uuid
from datetime import datetime
from pathlib import Path

from .models import Message
from .taskbox import Taskbox

_TASK_TEMPLATE = """\
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
"""


async def run_worker(
    agent_id: str,
    run_id: str,
    task_id: str,
    task_description: str,
    worktree_path: Path,
    taskbox: Taskbox,
    timeout: int = 120,
    claude_cmd: str = "claude",
) -> None:
    short_desc = task_description[:50].replace("\n", " ")
    (worktree_path / "TASK.md").write_text(
        _TASK_TEMPLATE.format(
            description=task_description,
            run_id=run_id,
            agent_id=agent_id,
            short_desc=short_desc,
        )
    )

    taskbox.update_agent_status(agent_id, "working")

    try:
        proc = await asyncio.create_subprocess_exec(
            claude_cmd,
            "--print",
            "Please complete the task described in TASK.md",
            cwd=worktree_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        taskbox.update_agent_status(agent_id, "working", pid=proc.pid)

        async def _drain_stdout() -> None:
            assert proc.stdout
            async for line in proc.stdout:
                taskbox.send_message(
                    Message(
                        id=str(uuid.uuid4()),
                        type="PROGRESS",
                        from_agent=agent_id,
                        to_agent="manager",
                        payload={"line": line.decode().rstrip()},
                        created_at=datetime.utcnow(),
                    )
                )

        try:
            await asyncio.wait_for(
                asyncio.gather(proc.wait(), _drain_stdout()),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            taskbox.send_message(
                Message(
                    id=str(uuid.uuid4()),
                    type="ERROR",
                    from_agent=agent_id,
                    to_agent="manager",
                    payload={"task_id": task_id, "error": "timeout"},
                    created_at=datetime.utcnow(),
                )
            )
            taskbox.update_agent_status(agent_id, "failed")
            return

        if proc.returncode == 0:
            taskbox.send_message(
                Message(
                    id=str(uuid.uuid4()),
                    type="COMPLETE",
                    from_agent=agent_id,
                    to_agent="manager",
                    payload={"task_id": task_id},
                    created_at=datetime.utcnow(),
                )
            )
            taskbox.update_agent_status(agent_id, "done")
        else:
            stderr = b""
            if proc.stderr:
                stderr = await proc.stderr.read()
            taskbox.send_message(
                Message(
                    id=str(uuid.uuid4()),
                    type="ERROR",
                    from_agent=agent_id,
                    to_agent="manager",
                    payload={
                        "task_id": task_id,
                        "returncode": proc.returncode,
                        "stderr": stderr.decode(),
                    },
                    created_at=datetime.utcnow(),
                )
            )
            taskbox.update_agent_status(agent_id, "failed")

    except Exception as exc:
        taskbox.send_message(
            Message(
                id=str(uuid.uuid4()),
                type="ERROR",
                from_agent=agent_id,
                to_agent="manager",
                payload={"task_id": task_id, "error": str(exc)},
                created_at=datetime.utcnow(),
            )
        )
        taskbox.update_agent_status(agent_id, "failed")
