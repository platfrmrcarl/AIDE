import asyncio
import stat
import pytest
from aide.models import AgentRecord
from aide.worker import run_worker


def make_agent(db, worktree):
    agent = AgentRecord(
        id="a1", run_id="r1", worktree_path=str(worktree),
        branch="aide/r1/a1", task_id="t1",
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
        timeout=10, worker_cmd="true",
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
        timeout=10, worker_cmd="false",
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
        timeout=10, worker_cmd="true",
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
        timeout=1, worker_cmd=str(script),
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
        timeout=10, worker_cmd="true",
    )
    agents = db.get_agents("r1")
    assert agents[0].status in ("done", "failed")


@pytest.mark.asyncio
async def test_worker_auto_cmd_errors_when_no_cli_found(db, tmp_path, mocker):
    """worker_cmd='auto' with no CLI installed sends ERROR message."""
    mocker.patch("aide.worker.detect_worker_cmd", return_value=None)
    make_agent(db, tmp_path)
    await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do the thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, worker_cmd="auto",
    )
    messages = db.get_unprocessed_messages("manager")
    error_msgs = [m for m in messages if m.type == "ERROR"]
    assert len(error_msgs) == 1
    assert "worker CLI" in error_msgs[0].payload.get("error", "")


@pytest.mark.asyncio
async def test_worker_bare_mode_writes_bare_template(db, tmp_path):
    make_agent(db, tmp_path)
    await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Generate three business names for a coffee shop",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, worker_cmd="true",
        mode="bare",
    )
    content = (tmp_path / "TASK.md").read_text()
    assert "OUTPUT.md" in content
    assert "git commit" not in content


@pytest.mark.asyncio
async def test_worker_git_mode_writes_git_template(db, tmp_path):
    make_agent(db, tmp_path)
    await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Add input validation",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, worker_cmd="true",
        mode="git",
    )
    content = (tmp_path / "TASK.md").read_text()
    assert "git commit" in content
    assert "OUTPUT.md" not in content


@pytest.mark.asyncio
async def test_worker_returns_true_on_success(db, tmp_path):
    make_agent(db, tmp_path)
    result = await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do the thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, worker_cmd="true",
    )
    assert result is True


@pytest.mark.asyncio
async def test_worker_returns_false_on_failure(db, tmp_path):
    make_agent(db, tmp_path)
    result = await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do the thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, worker_cmd="false",
    )
    assert result is False


@pytest.mark.asyncio
async def test_worker_returns_false_on_timeout(db, tmp_path):
    import stat
    make_agent(db, tmp_path)
    script = tmp_path / "slow.sh"
    script.write_text("#!/bin/sh\nsleep 100\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    result = await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do the thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=1, worker_cmd=str(script),
    )
    assert result is False


@pytest.mark.asyncio
async def test_worker_silent_suppresses_routing_messages(db, tmp_path):
    make_agent(db, tmp_path)
    result = await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do the thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, worker_cmd="true", silent=True,
    )
    assert result is True
    messages = db.get_unprocessed_messages("manager")
    assert not any(m.type in ("COMPLETE", "ERROR") for m in messages)


@pytest.mark.asyncio
async def test_worker_not_silent_sends_complete(db, tmp_path):
    make_agent(db, tmp_path)
    await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do the thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, worker_cmd="true", silent=False,
    )
    messages = db.get_unprocessed_messages("manager")
    assert any(m.type == "COMPLETE" for m in messages)


@pytest.mark.asyncio
async def test_worker_progress_callback_called(db, tmp_path):
    make_agent(db, tmp_path)
    received: list[tuple[str, str]] = []

    def _cb(agent_id: str, line: str) -> None:
        received.append((agent_id, line))

    script = tmp_path / "echo_worker.sh"
    script.write_text("#!/bin/sh\necho 'hello from agent'\n")
    script.chmod(script.stat().st_mode | 0o111)

    await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, worker_cmd=str(script),
        progress_callback=_cb,
    )

    assert any("hello from agent" in line for _, line in received)
    assert all(agent_id == "a1" for agent_id, _ in received)


@pytest.mark.asyncio
async def test_worker_no_callback_still_works(db, tmp_path):
    make_agent(db, tmp_path)
    result = await run_worker(
        agent_id="a1", run_id="r1", task_id="t1",
        task_description="Do thing",
        worktree_path=tmp_path, taskbox=db,
        timeout=10, worker_cmd="true",
    )
    assert result is True
