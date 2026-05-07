import json
import pytest
from unittest.mock import MagicMock, patch
from aide.models import Plan, SubTask
from aide.planner import compute_agent_count, plan_task

MOCK_API_RESPONSE = json.dumps({
    "complexity_score": 25,
    "agent_count": 6,
    "tasks": [
        {"id": "t1", "description": "Set up project structure", "depends_on": []},
        {"id": "t2", "description": "Implement auth module", "depends_on": ["t1"]},
        {"id": "t3", "description": "Write tests", "depends_on": ["t2"]},
    ],
})


def test_compute_agent_count_trivial():
    assert compute_agent_count(10) == 3


def test_compute_agent_count_small():
    count = compute_agent_count(30)
    assert 5 <= count <= 10


def test_compute_agent_count_medium():
    count = compute_agent_count(50)
    assert 10 <= count <= 20


def test_compute_agent_count_large():
    count = compute_agent_count(70)
    assert 20 <= count <= 50


def test_compute_agent_count_very_large():
    assert compute_agent_count(90) >= 50


def test_plan_task_returns_plan(mocker):
    mocker.patch("aide.providers.anthropic.generate", return_value=MOCK_API_RESPONSE)
    plan = plan_task("Build a REST API", provider="anthropic")
    assert isinstance(plan, Plan)
    assert plan.complexity_score == 25
    assert len(plan.tasks) == 3
    assert plan.tasks[0].id == "t1"
    assert plan.tasks[1].depends_on == ["t1"]


def test_plan_task_agent_count_override(mocker):
    mocker.patch("aide.providers.anthropic.generate", return_value=MOCK_API_RESPONSE)
    plan = plan_task("Build a REST API", provider="anthropic", agent_count_override=42)
    assert plan.agent_count == 42


def test_plan_task_handles_json_in_code_block(mocker):
    wrapped = f"```json\n{MOCK_API_RESPONSE}\n```"
    mocker.patch("aide.providers.anthropic.generate", return_value=wrapped)
    plan = plan_task("Build a REST API", provider="anthropic")
    assert len(plan.tasks) == 3


def test_plan_task_subtask_types(mocker):
    mocker.patch("aide.providers.anthropic.generate", return_value=MOCK_API_RESPONSE)
    plan = plan_task("Build a REST API", provider="anthropic")
    for task in plan.tasks:
        assert isinstance(task, SubTask)
        assert task.status == "pending"


def test_plan_task_uses_provider_generate(mocker):
    mocker.patch("aide.providers.anthropic.generate", return_value=MOCK_API_RESPONSE)
    plan = plan_task("Build a REST API", provider="anthropic")
    assert isinstance(plan, Plan)
    assert len(plan.tasks) == 3


def test_plan_task_openai_provider(mocker):
    mocker.patch("aide.providers.openai.generate", return_value=MOCK_API_RESPONSE)
    plan = plan_task("Build a REST API", provider="openai", model="gpt-4o")
    assert isinstance(plan, Plan)


def test_plan_task_unknown_provider_raises():
    with pytest.raises(ValueError, match="Unknown provider"):
        plan_task("task", provider="fakeprovider")
