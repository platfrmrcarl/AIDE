import subprocess
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from aide.judge import VariantCandidate, _get_diff


def _make_git_repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, capture_output=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, capture_output=True)
    (tmp_path / "README.md").write_text("init")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "feature.py").write_text("def f(): return 1\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "feat: add feature"], cwd=tmp_path, check=True, capture_output=True)
    return tmp_path


def test_variant_candidate_fields(tmp_path):
    c = VariantCandidate(agent_id="a1", slot_path=tmp_path, branch="aide/run/a1")
    assert c.agent_id == "a1"
    assert c.slot_path == tmp_path
    assert c.branch == "aide/run/a1"


def test_get_diff_git_mode(tmp_path):
    slot = _make_git_repo(tmp_path)
    candidate = VariantCandidate(agent_id="a1", slot_path=slot, branch="aide/run/a1")
    from aide.workspace import GitWorkspace
    mock_ws = MagicMock(spec=GitWorkspace)
    diff = _get_diff(candidate, mock_ws)
    assert "feature.py" in diff or "feat: add feature" in diff


def test_get_diff_bare_mode_with_output_md(tmp_path):
    (tmp_path / "OUTPUT.md").write_text("# Result\nSome output here\n")
    candidate = VariantCandidate(agent_id="a1", slot_path=tmp_path, branch="slot1")
    mock_ws = MagicMock()  # not a GitWorkspace
    diff = _get_diff(candidate, mock_ws)
    assert diff == "# Result\nSome output here\n"


def test_get_diff_bare_mode_no_output_md(tmp_path):
    candidate = VariantCandidate(agent_id="a1", slot_path=tmp_path, branch="slot1")
    mock_ws = MagicMock()  # not a GitWorkspace
    diff = _get_diff(candidate, mock_ws)
    assert diff == ""
