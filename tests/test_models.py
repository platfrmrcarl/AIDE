from datetime import datetime
import pytest
from aide.models import SubTask, Plan, Message, AgentRecord, RunRecord


def test_subtask_defaults():
    t = SubTask(id="t1", description="Do thing", depends_on=[])
    assert t.status == "pending"
    assert t.assigned_agent is None
    assert t.worktree_path is None
    assert t.branch is None


def test_subtask_with_deps():
    t = SubTask(id="t2", description="Do other thing", depends_on=["t1"])
    assert t.depends_on == ["t1"]


def test_plan_creation():
    tasks = [SubTask(id="t1", description="task", depends_on=[])]
    plan = Plan(run_id="abc", original_prompt="do stuff", agent_count=3,
                complexity_score=15, tasks=tasks)
    assert len(plan.tasks) == 1
    assert plan.agent_count == 3


def test_message_defaults():
    msg = Message(id="m1", type="DISPATCH", from_agent="manager",
                  to_agent="agent-001", payload={"task_id": "t1"})
    assert msg.processed is False
    assert isinstance(msg.created_at, datetime)


def test_agent_record_defaults():
    agent = AgentRecord(id="a1", run_id="r1", worktree_path="/tmp/wt",
                        branch="aide/r1/a1", task_id="t1")
    assert agent.status == "idle"
    assert agent.pid is None
    assert isinstance(agent.last_heartbeat, datetime)


def test_run_record_defaults():
    run = RunRecord(id="r1", prompt="do stuff", agent_count=3, complexity_score=15)
    assert run.status == "running"
    assert run.completed_at is None
    assert isinstance(run.started_at, datetime)
