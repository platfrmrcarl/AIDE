import subprocess
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from aide.judge import VariantCandidate, _get_diff, select_winner


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


def _make_candidates(tmp_path, n=2):
    candidates = []
    for i in range(n):
        p = tmp_path / f"slot{i}"
        p.mkdir()
        (p / "OUTPUT.md").write_text(f"output {i}")
        candidates.append(VariantCandidate(agent_id=f"agent-{i:03d}", slot_path=p, branch=f"b{i}"))
    return candidates


def _mock_provider(winner_id: str):
    mod = MagicMock()
    mod.generate.return_value = f'{{"winner": "{winner_id}"}}'
    return mod


def test_select_winner_returns_correct_candidate(tmp_path):
    candidates = _make_candidates(tmp_path, n=2)
    mock_ws = MagicMock()
    with patch("aide.judge.get_provider", return_value=_mock_provider("agent-001")), \
         patch("aide.judge._get_diff", return_value="diff text"):
        winner = select_winner("Build a feature", candidates, mock_ws)
    assert winner.agent_id == "agent-001"


def test_select_winner_fallback_on_invalid_json(tmp_path):
    candidates = _make_candidates(tmp_path, n=2)
    mock_ws = MagicMock()
    bad_provider = MagicMock()
    bad_provider.generate.return_value = "not json at all"
    with patch("aide.judge.get_provider", return_value=bad_provider), \
         patch("aide.judge._get_diff", return_value="diff"):
        winner = select_winner("Build a feature", candidates, mock_ws)
    assert winner is candidates[0]


def test_select_winner_fallback_on_unknown_agent_id(tmp_path):
    candidates = _make_candidates(tmp_path, n=2)
    mock_ws = MagicMock()
    with patch("aide.judge.get_provider", return_value=_mock_provider("agent-UNKNOWN")), \
         patch("aide.judge._get_diff", return_value="diff"):
        winner = select_winner("Build a feature", candidates, mock_ws)
    assert winner is candidates[0]


def test_select_winner_fallback_on_exception(tmp_path):
    candidates = _make_candidates(tmp_path, n=2)
    mock_ws = MagicMock()
    exc_provider = MagicMock()
    exc_provider.generate.side_effect = RuntimeError("API down")
    with patch("aide.judge.get_provider", return_value=exc_provider), \
         patch("aide.judge._get_diff", return_value="diff"):
        winner = select_winner("Build a feature", candidates, mock_ws)
    assert winner is candidates[0]


def test_select_winner_raises_on_unknown_provider(tmp_path):
    candidates = _make_candidates(tmp_path, n=2)
    mock_ws = MagicMock()
    with pytest.raises(ValueError, match="Unknown provider"):
        select_winner("task", candidates, mock_ws, provider="nonexistent")
