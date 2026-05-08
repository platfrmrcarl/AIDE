import pytest
from datetime import datetime
from aide.taskbox import Taskbox
from aide.models import SubTask, Message, AgentRecord, RunRecord


def test_init_creates_tables(db):
    conn = db._conn()
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert {"tasks", "messages", "agents", "runs"}.issubset(tables)


def test_save_and_get_task(db):
    task = SubTask(id="t1", description="Do thing", depends_on=["t0"])
    db.save_task(task, "run1")
    tasks = db.get_tasks("run1")
    assert len(tasks) == 1
    assert tasks[0].id == "t1"
    assert tasks[0].depends_on == ["t0"]


def test_update_task_status(db):
    db.save_task(SubTask(id="t1", description="Do thing", depends_on=[]), "run1")
    db.update_task_status("t1", "complete")
    tasks = db.get_tasks("run1")
    assert tasks[0].status == "complete"


def test_get_pending_tasks(db):
    db.save_task(SubTask(id="t1", description="A", depends_on=[]), "run1")
    db.save_task(SubTask(id="t2", description="B", depends_on=[]), "run1")
    db.update_task_status("t1", "complete")
    pending = db.get_pending_tasks("run1")
    assert len(pending) == 1
    assert pending[0].id == "t2"


def test_get_completed_task_ids(db):
    db.save_task(SubTask(id="t1", description="A", depends_on=[]), "run1")
    db.save_task(SubTask(id="t2", description="B", depends_on=[]), "run1")
    db.update_task_status("t1", "complete")
    completed = db.get_completed_task_ids("run1")
    assert completed == {"t1"}


def test_message_roundtrip(db):
    msg = Message(id="m1", type="COMPLETE", from_agent="a1", to_agent="manager",
                  payload={"task_id": "t1"}, created_at=datetime.utcnow())
    db.send_message(msg)
    messages = db.get_unprocessed_messages("manager")
    assert len(messages) == 1
    assert messages[0].type == "COMPLETE"
    assert messages[0].payload == {"task_id": "t1"}


def test_mark_message_processed(db):
    msg = Message(id="m1", type="COMPLETE", from_agent="a1", to_agent="manager",
                  payload={}, created_at=datetime.utcnow())
    db.send_message(msg)
    db.mark_message_processed("m1")
    messages = db.get_unprocessed_messages("manager")
    assert len(messages) == 0


def test_save_and_get_run(db):
    run = RunRecord(id="r1", prompt="do stuff", agent_count=3, complexity_score=15)
    db.save_run(run)
    retrieved = db.get_run("r1")
    assert retrieved is not None
    assert retrieved.prompt == "do stuff"
    assert retrieved.status == "running"


def test_get_run_missing(db):
    assert db.get_run("nope") is None


def test_save_and_get_agents(db):
    agent = AgentRecord(id="a1", run_id="r1", worktree_path="/tmp/wt",
                        branch="aide/r1/a1", task_id="t1")
    db.save_agent(agent)
    agents = db.get_agents("r1")
    assert len(agents) == 1
    assert agents[0].id == "a1"


def test_update_agent_status(db):
    agent = AgentRecord(id="a1", run_id="r1", worktree_path="/tmp/wt",
                        branch="aide/r1/a1", task_id="t1")
    db.save_agent(agent)
    db.update_agent_status("a1", "working", pid=12345)
    agents = db.get_agents("r1")
    assert agents[0].status == "working"
    assert agents[0].pid == 12345


def test_taskbox_uses_wal_mode(tmp_path):
    from aide.taskbox import Taskbox
    db = Taskbox(tmp_path / "aide.db")
    with db._conn() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


def test_reset_failed_tasks(db, tmp_path):
    from aide.models import SubTask
    run_id = "r1"
    task = SubTask(id="t1", description="thing", depends_on=[])
    db.save_task(task, run_id)
    db.update_task_status("t1", "failed")

    count = db.reset_failed_tasks(run_id)

    assert count == 1
    tasks = db.get_tasks(run_id)
    assert tasks[0].status == "pending"


def test_reset_failed_tasks_leaves_complete_untouched(db, tmp_path):
    from aide.models import SubTask
    run_id = "r1"
    for tid, status in [("t1", "complete"), ("t2", "failed")]:
        task = SubTask(id=tid, description="thing", depends_on=[])
        db.save_task(task, run_id)
        db.update_task_status(tid, status)

    count = db.reset_failed_tasks(run_id)

    assert count == 1
    tasks = {t.id: t for t in db.get_tasks(run_id)}
    assert tasks["t1"].status == "complete"
    assert tasks["t2"].status == "pending"
