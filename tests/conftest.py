
import subprocess
import tempfile
import pytest
from pathlib import Path
from click.testing import CliRunner
from galaxy.taskbox import Taskbox


@pytest.fixture
def git_repo():
    with tempfile.TemporaryDirectory() as d:
        repo = Path(d)
        subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=repo, capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, capture_output=True)
        (repo / "README.md").write_text("test")
        subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)
        yield repo


@pytest.fixture
def db(tmp_path):
    return Taskbox(tmp_path / "test.db")


@pytest.fixture
def runner():
    return CliRunner()
