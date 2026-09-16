from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from pt.config import Settings
from pt.state import State

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    """A throwaway portfolio root with one real git repo (`alpha`) that has
    two commits and a `.lavish/` page, and an eval run under `runs/`."""
    root = tmp_path / "portfolio"
    alpha = root / "alpha"
    (alpha / "src").mkdir(parents=True)
    env = {
        "GIT_AUTHOR_NAME": "dev",
        "GIT_AUTHOR_EMAIL": "dev@example.com",
        "GIT_COMMITTER_NAME": "dev",
        "GIT_COMMITTER_EMAIL": "dev@example.com",
        "GIT_AUTHOR_DATE": "2026-09-10T03:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-09-10T03:00:00+00:00",
    }

    def git(*a: str) -> None:
        subprocess.run(
            ["git", "-C", str(alpha), *a],
            check=True,
            capture_output=True,
            env={**env, "PATH": "/usr/bin:/bin:/opt/homebrew/bin"},
        )

    git("init", "-q", "-b", "main")
    (alpha / "src" / "core.py").write_text("x = 1\n")
    git("add", "-A")
    git("commit", "-q", "-m", "feat: core")
    git("remote", "add", "no-mistakes", "/Users/dev/.no-mistakes/repos/8a19743e7d19.git")
    git("checkout", "-q", "-b", "feature/x")
    (alpha / "src" / "core.py").write_text("x = 2\ny = 3\n")
    git("commit", "-q", "-am", "fix: bump")
    (alpha / ".lavish").mkdir()
    (alpha / ".lavish" / "s00_plan.html").write_text(
        "<html><head><title>Alpha plan</title></head><body></body></html>"
    )
    (alpha / "runs" / "20260910T030000Z_run").mkdir(parents=True)
    (alpha / "runs" / "20260910T030000Z_run" / "run.json").write_text(
        '{"run_id": "r1", "agent": "v2", "model": "claude-haiku-4-5", "n_tasks": 10, "started_at": "2026-09-10T03:00:00Z", "summary": {"accuracy": 0.8, "n": 10}}'
    )
    (root / "beta").mkdir()
    (root / "beta" / ".git").mkdir()
    return root


@pytest.fixture
def settings(tmp_path: Path, repo_root: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        state_dir=tmp_path / "state",
        claude_dir=FIXTURES / "claude",
        codex_dir=FIXTURES / "codex",
        nomistakes_dir=FIXTURES / "nomistakes",
        # The static fixtures use /Users/dev/git/portfolio as their root; it need
        # not exist for path → project mapping to work.
        repo_roots=(repo_root, Path("/Users/dev/git/portfolio")),
        timezone="Australia/Sydney",
    )


@pytest.fixture
def state(settings: Settings) -> State:
    return State(settings.state_dir / "state.json")
