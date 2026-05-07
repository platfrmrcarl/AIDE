import json
import sqlite3
from datetime import datetime
from pathlib import Path

from .models import AgentRecord, Message, RunRecord, SubTask


class Taskbox:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._init_db()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    description TEXT NOT NULL,
                    depends_on TEXT NOT NULL DEFAULT '[]',
                    assigned_agent TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    worktree_path TEXT,
                    branch TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    from_agent TEXT NOT NULL,
                    to_agent TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    processed INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS agents (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    worktree_path TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    pid INTEGER,
                    status TEXT NOT NULL DEFAULT 'idle',
                    last_heartbeat TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    prompt TEXT NOT NULL,
                    agent_count INTEGER NOT NULL,
                    complexity_score INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'running',
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                );
            """)

    def save_run(self, run: RunRecord) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO runs VALUES (?,?,?,?,?,?,?)",
                (
                    run.id, run.prompt, run.agent_count, run.complexity_score,
                    run.status, run.started_at.isoformat(),
                    run.completed_at.isoformat() if run.completed_at else None,
                ),
            )

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if not row:
            return None
        return RunRecord(
            id=row["id"], prompt=row["prompt"], agent_count=row["agent_count"],
            complexity_score=row["complexity_score"], status=row["status"],
            started_at=datetime.fromisoformat(row["started_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
        )

    def save_task(self, task: SubTask, run_id: str) -> None:
        now = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO tasks VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    task.id, run_id, task.description, json.dumps(task.depends_on),
                    task.assigned_agent, task.status, task.worktree_path, task.branch,
                    now, now,
                ),
            )

    def update_task_status(self, task_id: str, status: str, **kwargs: object) -> None:
        sets = ["status=?", "updated_at=?"]
        params: list[object] = [status, datetime.utcnow().isoformat()]
        for key, val in kwargs.items():
            sets.append(f"{key}=?")
            params.append(val)
        params.append(task_id)
        with self._conn() as conn:
            conn.execute(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", params)

    def get_tasks(self, run_id: str) -> list[SubTask]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM tasks WHERE run_id=?", (run_id,)).fetchall()
        return [
            SubTask(
                id=r["id"], description=r["description"],
                depends_on=json.loads(r["depends_on"]),
                status=r["status"], assigned_agent=r["assigned_agent"],
                worktree_path=r["worktree_path"], branch=r["branch"],
            )
            for r in rows
        ]

    def get_pending_tasks(self, run_id: str) -> list[SubTask]:
        return [t for t in self.get_tasks(run_id) if t.status == "pending"]

    def get_completed_task_ids(self, run_id: str) -> set[str]:
        return {t.id for t in self.get_tasks(run_id) if t.status == "complete"}

    def send_message(self, msg: Message) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO messages VALUES (?,?,?,?,?,?,?)",
                (
                    msg.id, msg.type, msg.from_agent, msg.to_agent,
                    json.dumps(msg.payload), msg.created_at.isoformat(), 0,
                ),
            )

    def get_unprocessed_messages(self, to_agent: str) -> list[Message]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM messages WHERE to_agent=? AND processed=0 ORDER BY created_at",
                (to_agent,),
            ).fetchall()
        return [
            Message(
                id=r["id"], type=r["type"], from_agent=r["from_agent"],
                to_agent=r["to_agent"], payload=json.loads(r["payload"]),
                created_at=datetime.fromisoformat(r["created_at"]),
                processed=bool(r["processed"]),
            )
            for r in rows
        ]

    def mark_message_processed(self, msg_id: str) -> None:
        with self._conn() as conn:
            conn.execute("UPDATE messages SET processed=1 WHERE id=?", (msg_id,))

    def save_agent(self, agent: AgentRecord) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO agents VALUES (?,?,?,?,?,?,?,?)",
                (
                    agent.id, agent.run_id, agent.worktree_path, agent.branch,
                    agent.task_id, agent.pid, agent.status,
                    agent.last_heartbeat.isoformat(),
                ),
            )

    def update_agent_status(self, agent_id: str, status: str, pid: int | None = None) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE agents SET status=?, last_heartbeat=?, pid=? WHERE id=?",
                (status, datetime.utcnow().isoformat(), pid, agent_id),
            )

    def list_runs(self) -> list[RunRecord]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM runs ORDER BY started_at DESC").fetchall()
        return [
            RunRecord(
                id=row["id"], prompt=row["prompt"], agent_count=row["agent_count"],
                complexity_score=row["complexity_score"], status=row["status"],
                started_at=datetime.fromisoformat(row["started_at"]),
                completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            )
            for row in rows
        ]

    def get_agents(self, run_id: str) -> list[AgentRecord]:
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM agents WHERE run_id=?", (run_id,)).fetchall()
        return [
            AgentRecord(
                id=r["id"], run_id=r["run_id"], worktree_path=r["worktree_path"],
                branch=r["branch"], task_id=r["task_id"], pid=r["pid"],
                status=r["status"],
                last_heartbeat=datetime.fromisoformat(r["last_heartbeat"]),
            )
            for r in rows
        ]
