import asyncio
import json
import os
import re
import uuid

from anthropic import Anthropic

from .models import Plan, SubTask

_SYSTEM_PROMPT = """You are a software engineering task decomposition expert.
Given a coding task, assess complexity (1-100) and break it into atomic subtasks.

Agent count guidelines:
- Score 1-20: 3 agents (bug fix, trivial change)
- Score 21-40: 5-10 agents (small feature)
- Score 41-60: 10-20 agents (medium feature with tests)
- Score 61-80: 20-50 agents (multi-module feature)
- Score 81-100: 50-100 agents (full project)

Respond ONLY with valid JSON (no preamble, no explanation, no code fences):
{
  "complexity_score": <int 1-100>,
  "agent_count": <int>,
  "tasks": [
    {"id": "t1", "description": "<actionable task>", "depends_on": []}
  ]
}

Rules:
- Each task must be independently executable by one AI coding agent
- Tasks must form a valid DAG (no cycles)
- Include file names in descriptions where possible
- depends_on lists IDs of prerequisite tasks
"""


def compute_agent_count(complexity_score: int) -> int:
    if complexity_score <= 20:
        return 3
    if complexity_score <= 40:
        return max(5, complexity_score // 5)
    if complexity_score <= 60:
        return max(10, complexity_score // 4)
    if complexity_score <= 80:
        return max(20, complexity_score // 2)
    return max(50, complexity_score)


def _build_planning_prompt(prompt: str, agent_count_override: int | None) -> str:
    override_note = (
        f"\n\nNote: Use agent_count={agent_count_override} in your response."
        if agent_count_override is not None
        else ""
    )
    return f"Task: {prompt}{override_note}"


def _parse_plan_response(raw: str, prompt: str, agent_count_override: int | None) -> Plan:
    run_id = str(uuid.uuid4())[:8]
    raw = raw.strip()
    match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", raw)
    if match:
        raw = match.group(1)

    data = json.loads(raw)

    agent_count = agent_count_override or compute_agent_count(data["complexity_score"])

    tasks = [
        SubTask(
            id=t["id"],
            description=t["description"],
            depends_on=t.get("depends_on", []),
        )
        for t in data["tasks"]
    ]

    return Plan(
        run_id=run_id,
        original_prompt=prompt,
        agent_count=agent_count,
        complexity_score=data["complexity_score"],
        tasks=tasks,
    )


async def _plan_via_cli(prompt: str, claude_cmd: str, agent_count_override: int | None) -> Plan:
    planning_prompt = _build_planning_prompt(prompt, agent_count_override)
    proc = await asyncio.create_subprocess_exec(
        claude_cmd, "--print", planning_prompt,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=120)
    raw = stdout.decode()
    return _parse_plan_response(raw, prompt, agent_count_override)


def plan_task(
    prompt: str,
    model: str = "claude-opus-4-7",
    agent_count_override: int | None = None,
    auth_mode: str = "api_key",   # "auto" | "api_key" | "claude_cli"
    claude_cmd: str = "claude",
) -> Plan:
    use_cli = False

    if auth_mode == "claude_cli":
        use_cli = True
    elif auth_mode == "api_key":
        use_cli = False
    else:  # auto
        use_cli = not bool(os.environ.get("ANTHROPIC_API_KEY"))

    if use_cli:
        return asyncio.run(_plan_via_cli(prompt, claude_cmd, agent_count_override))

    # API key path
    client = Anthropic()
    run_id = str(uuid.uuid4())[:8]

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": _build_planning_prompt(prompt, agent_count_override)}],
    )

    raw = response.content[0].text.strip()
    return _parse_plan_response(raw, prompt, agent_count_override)
