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


def _mock_anthropic(response_text: str):
    mock_content = MagicMock()
    mock_content.text = response_text
    mock_response = MagicMock()
    mock_response.content = [mock_content]
    mock_client = MagicMock()
    mock_client.messages.create.return_value = mock_response
    return mock_client


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


def test_plan_task_returns_plan():
    with patch("aide.planner.Anthropic", return_value=_mock_anthropic(MOCK_API_RESPONSE)):
        plan = plan_task("Build a REST API")

    assert isinstance(plan, Plan)
    assert plan.complexity_score == 25
    assert len(plan.tasks) == 3
    assert plan.tasks[0].id == "t1"
    assert plan.tasks[1].depends_on == ["t1"]


def test_plan_task_agent_count_override():
    with patch("aide.planner.Anthropic", return_value=_mock_anthropic(MOCK_API_RESPONSE)):
        plan = plan_task("Build a REST API", agent_count_override=42)

    assert plan.agent_count == 42


def test_plan_task_handles_json_in_code_block():
    wrapped = f"```json\n{MOCK_API_RESPONSE}\n```"
    with patch("aide.planner.Anthropic", return_value=_mock_anthropic(wrapped)):
        plan = plan_task("Build a REST API")

    assert len(plan.tasks) == 3


def test_plan_task_subtask_types():
    with patch("aide.planner.Anthropic", return_value=_mock_anthropic(MOCK_API_RESPONSE)):
        plan = plan_task("Build a REST API")

    for task in plan.tasks:
        assert isinstance(task, SubTask)
        assert task.status == "pending"


def _make_mock_plan():
    return Plan(
        run_id="test1234",
        original_prompt="Build a REST API",
        agent_count=6,
        complexity_score=25,
        tasks=[
            SubTask(id="t1", description="Set up project structure", depends_on=[]),
            SubTask(id="t2", description="Implement auth module", depends_on=["t1"]),
            SubTask(id="t3", description="Write tests", depends_on=["t2"]),
        ],
    )


def test_plan_task_uses_cli_when_no_api_key(mocker):
    """When auth_mode=claude_cli, uses subprocess not Anthropic SDK."""
    mock_plan = _make_mock_plan()
    mocker.patch("aide.planner.asyncio.run", return_value=mock_plan)
    mock_anthropic_cls = mocker.patch("aide.planner.Anthropic")

    plan = plan_task("Build a REST API", auth_mode="claude_cli")

    assert isinstance(plan, Plan)
    assert len(plan.tasks) == 3
    mock_anthropic_cls.assert_not_called()


def test_plan_task_auto_falls_back_to_cli(mocker, monkeypatch):
    """auth_mode=auto with no ANTHROPIC_API_KEY falls back to CLI."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    mock_plan = _make_mock_plan()
    mocker.patch("aide.planner.asyncio.run", return_value=mock_plan)
    mock_anthropic_cls = mocker.patch("aide.planner.Anthropic")

    plan = plan_task("Build a REST API", auth_mode="auto")

    assert isinstance(plan, Plan)
    assert len(plan.tasks) == 3
    mock_anthropic_cls.assert_not_called()
