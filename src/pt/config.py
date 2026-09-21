"""Runtime configuration: where things live and how paths map to projects.

Everything is overridable by environment variable so the same code runs on
the laptop (collecting), in CI (rolling up) and in the demo container
(serving a baked snapshot with no home directory at all).
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

HOME = Path.home()


def _env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else default


@dataclass(frozen=True)
class Settings:
    # Local event store and rollups. `data/` is gitignored.
    data_dir: Path = field(default_factory=lambda: _env_path("PT_DATA_DIR", Path("data")))
    # Collector state (byte offsets, last-seen ids) lives outside the repo.
    state_dir: Path = field(default_factory=lambda: _env_path("PT_STATE_DIR", HOME / ".pt"))
    # Sources.
    claude_dir: Path = field(default_factory=lambda: _env_path("PT_CLAUDE_DIR", HOME / ".claude"))
    codex_dir: Path = field(default_factory=lambda: _env_path("PT_CODEX_DIR", HOME / ".codex"))
    nomistakes_dir: Path = field(
        default_factory=lambda: _env_path("PT_NOMISTAKES_DIR", HOME / ".no-mistakes")
    )
    # A recorded `pmset -g log` to read instead of shelling out (tests, replay).
    pmset_log: Path | None = field(
        default_factory=lambda: (
            Path(os.environ["PT_PMSET_LOG"]).expanduser()
            if os.environ.get("PT_PMSET_LOG")
            else None
        )
    )
    # Apple's Screen Time store; reading it needs Full Disk Access.
    knowledge_db: Path = field(
        default_factory=lambda: _env_path(
            "PT_KNOWLEDGE_DB", HOME / "Library/Application Support/Knowledge/knowledgeC.db"
        )
    )
    # Repo roots, in priority order. The first path component after a root is
    # the project name; older roots are kept so sessions recorded before a
    # move still attribute correctly (a `cwd` never changes retroactively).
    repo_roots: tuple[Path, ...] = field(
        default_factory=lambda: tuple(
            Path(p).expanduser()
            for p in os.environ.get(
                "PT_REPO_ROOTS",
                f"{HOME}/git/nmp-ai-portfolio:{HOME}/git/nmp-projects:{HOME}/git",
            ).split(":")
            if p
        )
    )
    github_owner: str = field(default_factory=lambda: os.environ.get("PT_GITHUB_OWNER", "nmp-dsci"))
    # Day bucketing for rollups. Events carry UTC; days are local.
    timezone: str = field(default_factory=lambda: os.environ.get("PT_TZ", "Australia/Sydney"))
    # Cloud.
    s3_bucket: str | None = field(default_factory=lambda: os.environ.get("PT_S3_BUCKET"))
    aws_region: str = field(default_factory=lambda: os.environ.get("AWS_REGION", "ap-southeast-2"))
    # Public demo: read-only, aggregates only, no keys.
    demo_mode: bool = field(default_factory=lambda: os.environ.get("PT_DEMO_MODE", "") == "1")
    ingest_secret: str | None = field(default_factory=lambda: os.environ.get("PT_INGEST_SECRET"))

    @property
    def events_dir(self) -> Path:
        return self.data_dir / "events"

    @property
    def rollups_dir(self) -> Path:
        return self.data_dir / "rollups"

    def project_from_path(self, path: str | os.PathLike[str] | None) -> str | None:
        """Map a working directory to a project name via the configured roots.

        `/Users/x/git/nmp-ai-portfolio/DABStep-loop/src` → `DABStep-loop`.
        Worktrees and scratch dirs under a project still resolve to it.
        """
        if not path:
            return None
        p = Path(path).expanduser()
        for root in self.repo_roots:
            try:
                rel = p.resolve().relative_to(root.resolve())
            except (ValueError, OSError):
                try:
                    rel = p.relative_to(root)
                except ValueError:
                    continue
            if rel.parts:
                return rel.parts[0]
        text = str(p)
        # no-mistakes runs the agent inside ~/.no-mistakes/worktrees/<gate>/<run>;
        # the gate hash maps back to a repo through that repo's remote.
        m = re.search(r"/\.no-mistakes/worktrees/([0-9a-f]+)/", text)
        if m:
            return _gate_projects(self.repo_roots).get(m.group(1) + ".git")
        # Claude Code scratchpads live under /private/tmp/claude-<uid>/<slug>/…
        # where the slug is the project path with '/' → '-'. Match the longest
        # known project name inside it.
        best = max(
            (n for n in self.known_projects() if f"-{n}/" in text or text.endswith(f"-{n}")),
            key=len,
            default=None,
        )
        return best

    def known_projects(self) -> tuple[str, ...]:
        names: list[str] = []
        for root in self.repo_roots:
            if root.is_dir():
                names += [c.name for c in root.iterdir() if (c / ".git").exists()]
        return tuple(dict.fromkeys(names))


@lru_cache(maxsize=4)
def _gate_projects(roots: tuple[Path, ...]) -> dict[str, str]:
    """`<hash>.git` → project name, from each repo's `no-mistakes` remote."""
    out: dict[str, str] = {}
    for root in roots:
        if not root.is_dir():
            continue
        for repo in root.iterdir():
            if not (repo / ".git").exists():
                continue
            r = subprocess.run(
                ["git", "-C", str(repo), "remote", "get-url", "no-mistakes"],
                capture_output=True,
                text=True,
                check=False,
            )
            if r.stdout.strip():
                out[Path(r.stdout.strip()).name] = repo.name
    return out


def gate_projects(settings: Settings) -> dict[str, str]:
    return _gate_projects(settings.repo_roots)


def settings() -> Settings:
    return Settings()
