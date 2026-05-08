import json
import os
import re
import subprocess
import warnings
from dataclasses import dataclass
from pathlib import Path

from .providers import SUPPORTED_PROVIDERS, get_provider


@dataclass
class VariantCandidate:
    agent_id: str
    slot_path: Path
    branch: str


def _get_diff(candidate: VariantCandidate, workspace) -> str:
    from .workspace import GitWorkspace
    if isinstance(workspace, GitWorkspace):
        result = subprocess.run(
            ["git", "show", "--stat", "--patch", "HEAD"],
            cwd=candidate.slot_path,
            capture_output=True,
            text=True,
        )
        return result.stdout[:8000]
    output_file = candidate.slot_path / "OUTPUT.md"
    return output_file.read_text() if output_file.exists() else ""


def _build_judge_prompt(
    task_description: str,
    candidates: list[VariantCandidate],
    workspace,
) -> str:
    parts = [
        f"Task: {task_description}\n\n"
        "Select the best implementation. Criteria: correctness, clarity, minimal diff size.\n"
    ]
    for c in candidates:
        diff = _get_diff(c, workspace)
        parts.append(f"\n[Candidate {c.agent_id}]\n{diff}\n")
    parts.append('\nRespond ONLY with valid JSON: {"winner": "<agent_id>"}')
    return "".join(parts)


def select_winner(
    task_description: str,
    candidates: list[VariantCandidate],
    workspace,
    provider: str = "anthropic",
    model: str | None = None,
) -> VariantCandidate:
    """Pick the best candidate using an LLM judge. Falls back to candidates[0] on any failure.

    Positional args (in order): task_description, candidates, workspace
    Keyword args: provider (raises ValueError if unknown), model (None = provider default)
    """
    if provider not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unknown provider '{provider}'. Supported: {', '.join(SUPPORTED_PROVIDERS)}"
        )
    meta = SUPPORTED_PROVIDERS[provider]
    resolved_model = model or meta["default_model"]
    api_key = os.environ.get(meta["api_key_env"])
    cli_cmd = meta.get("default_cli_cmd") or "claude"

    prompt = _build_judge_prompt(task_description, candidates, workspace)

    try:
        provider_mod = get_provider(provider)
        raw = provider_mod.generate(
            prompt=prompt,
            model=resolved_model,
            api_key=api_key,
            auth_mode="auto",
            cli_cmd=cli_cmd,
            system_prompt="You are a code quality judge. Select the best implementation.",
        )
        match = re.search(r"\{[^}]*\}", raw, re.DOTALL)
        if match:
            data = json.loads(match.group(0))
            winner_id = data.get("winner")
            for c in candidates:
                if c.agent_id == winner_id:
                    return c
    except Exception as exc:
        warnings.warn(f"Judge fallback ({provider}): {exc}")

    return candidates[0]
