"""Local git collector: commits and branch switches for every repo under the
configured roots — including work only pushed to a private gate remote.

`git log --all --source` attributes each commit to the ref it was reached
from, which is the closest thing to "which branch was this made on" that
git can answer after the fact.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Iterator
from pathlib import Path

from pt.collectors._util import repos_under
from pt.config import Settings
from pt.schema import Event, Source, event_id, utc
from pt.state import State

SOURCE: Source = "git_local"
_SEP = "\x1f"
_STAT = re.compile(
    r"(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?"
)
_CHECKOUT = re.compile(r"^(\S+) .*?checkout: moving from (\S+) to (\S+)$")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, timeout=120, check=False
    ).stdout


def _remote_repo(repo: Path, owner: str) -> str | None:
    for line in _git(repo, "remote", "-v").splitlines():
        m = re.search(r"github\.com[:/]([^/\s]+)/([^\s]+?)(?:\.git)?\s", line)
        if m:
            return f"{m.group(1)}/{m.group(2)}"
    return None


def commit_events(
    repo: Path, project: str, gh_repo: str | None, since: str | None
) -> Iterator[Event]:
    args = [
        "log",
        "--all",
        "--source",
        "--shortstat",
        "--date=iso-strict",
        f"--format=%x1e%H{_SEP}%aI{_SEP}%ae{_SEP}%S{_SEP}%s",
    ]
    if since:
        args.append(f"--since={since}")
    out = _git(repo, *args)
    for chunk in out.split("\x1e"):
        chunk = chunk.strip()
        if not chunk:
            continue
        head, _, rest = chunk.partition("\n")
        parts = head.split(_SEP)
        if len(parts) < 5:
            continue
        sha, ts, email, ref, subject = parts[:5]
        files = ins = dels = 0
        m = _STAT.search(rest)
        if m:
            files, ins, dels = (int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0))
        branch = ref.replace("refs/heads/", "").replace("refs/remotes/", "")
        yield Event(
            event_id=event_id(SOURCE, "commit", sha),
            source=SOURCE,
            kind="commit",
            ts=utc(ts),
            project=project,
            repo=gh_repo,
            branch=branch,
            meta={
                "sha": sha[:12],
                "files": files,
                "insertions": ins,
                "deletions": dels,
                "subject": subject[:80],
                "author": email.split("@")[0],
            },
        )


def switch_events(repo: Path, project: str, gh_repo: str | None) -> Iterator[Event]:
    out = _git(repo, "reflog", "--date=iso-strict", "--format=%H %gd %gs")
    for line in out.splitlines():
        m = _CHECKOUT.match(line)
        if not m:
            continue
        sha, src, dst = m.groups()
        tsm = re.search(r"HEAD@\{([^}]+)\}", line)
        if not tsm:
            continue
        ts = tsm.group(1)
        yield Event(
            event_id=event_id(SOURCE, "branch_switch", str(repo), sha, ts, dst),
            source=SOURCE,
            kind="branch_switch",
            ts=utc(ts),
            project=project,
            repo=gh_repo,
            branch=dst,
            meta={"from": src[:60]},
        )


def collect(settings: Settings, state: State) -> Iterator[Event]:
    for repo in repos_under(settings.repo_roots):
        project = repo.name
        gh_repo = _remote_repo(repo, settings.github_owner)
        key = f"git_since:{repo}"
        since = state.get(key)
        latest: str | None = since
        for ev in commit_events(repo, project, gh_repo, since):
            iso = ev.ts.isoformat()
            if latest is None or iso > latest:
                latest = iso
            yield ev
        yield from switch_events(repo, project, gh_repo)
        if latest:
            # Overlap by a day: `--since` is inclusive of the timestamp and
            # dedupe on sha makes re-reading a few commits free.
            state.set(key, latest)
