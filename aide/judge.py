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
