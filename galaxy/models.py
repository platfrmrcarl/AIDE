from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class SubTask:
    id: str
    description: str
    depends_on: list[str]
    status: Literal["pending", "in_progress", "complete", "failed"] = "pending"
    assigned_agent: str | None = None
    worktree_path: str | None = None
    branch: str | None = None


@dataclass
class Plan:
    run_id: str
    original_prompt: str
    agent_count: int
    complexity_score: int
    tasks: list[SubTask]


@dataclass
class Message:
    id: str
    type: Literal["DISPATCH", "PROGRESS", "COMPLETE", "ERROR", "ESCALATE", "SYNC"]
    from_agent: str
    to_agent: str
    payload: dict
    created_at: datetime = field(default_factory=datetime.utcnow)
    processed: bool = False


@dataclass
class AgentRecord:
    id: str
    run_id: str
    worktree_path: str
    branch: str
    task_id: str
    pid: int | None = None
    status: Literal["idle", "working", "done", "failed"] = "idle"
    last_heartbeat: datetime = field(default_factory=datetime.utcnow)


@dataclass
class RunRecord:
    id: str
    prompt: str
    agent_count: int
    complexity_score: int
    status: Literal["running", "complete", "failed"] = "running"
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
