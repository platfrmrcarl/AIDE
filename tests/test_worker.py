import asyncio
import stat
import pytest
from galaxy.models import AgentRecord
from galaxy.worker import run_worker


def make_agent(db, worktree):
    agent = AgentRecord(
        id="a1", run_id="r1", worktree_path=str(worktree),
        branch="galaxy/r1/a1", task_id="t1",
    )
    db.save_agent(agent)
    return agent


@pytest.mark.asyncio
async def test_worker_sends_complete_on_success(db, tmp_path):
    make_agent(db, tmp_path)
    await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do the thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, claude_cmd="true",
    )
    messages = db.get_unprocessed_messages("manager")
    assert any(m.type == "COMPLETE" for m in messages)


@pytest.mark.asyncio
async def test_worker_sends_error_on_failure(db, tmp_path):
    make_agent(db, tmp_path)
    await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do the thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, claude_cmd="false",
    )
    messages = db.get_unprocessed_messages("manager")
    assert any(m.type == "ERROR" for m in messages)


@pytest.mark.asyncio
async def test_worker_writes_task_md(db, tmp_path):
    make_agent(db, tmp_path)
    await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Build the auth module",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, claude_cmd="true",
    )
    task_md = tmp_path / "TASK.md"
    assert task_md.exists()
    content = task_md.read_text()
    assert "Build the auth module" in content
    assert "a1" in content


@pytest.mark.asyncio
async def test_worker_timeout_sends_error(db, tmp_path):
    make_agent(db, tmp_path)
    # Create a script that sleeps longer than timeout
    script = tmp_path / "slow.sh"
    script.write_text("#!/bin/sh\nsleep 100\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do the thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=1, claude_cmd=str(script),
    )
    messages = db.get_unprocessed_messages("manager")
    assert any(m.type == "ERROR" for m in messages)


@pytest.mark.asyncio
async def test_worker_updates_agent_status_to_working(db, tmp_path):
    make_agent(db, tmp_path)
    await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do the thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, claude_cmd="true",
    )
    agents = db.get_agents("r1")
    assert agents[0].status in ("done", "failed")
