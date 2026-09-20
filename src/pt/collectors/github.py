"""GitHub: webhook payload parsers (push side) and a REST backfill (pull side).

`nmp-dsci` is a user account, so there is no org-level webhook: `install_hooks`
creates one per repo with a shared HMAC secret. Backfill walks PRs, workflow
runs and deployments so history exists before the hooks did, and fills gaps.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from pt.config import Settings
from pt.schema import Event, Source, event_id, utc
from pt.state import State

SOURCE: Source = "github"
API = "https://api.github.com"
HOOK_EVENTS = [
    "push",
    "create",
    "delete",
    "pull_request",
    "pull_request_review",
    "workflow_run",
    "deployment_status",
    "release",
]


def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """GitHub sends `X-Hub-Signature-256: sha256=<hmac>`."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header[len("sha256=") :])


def _repo(payload: dict[str, Any]) -> tuple[str | None, str | None]:
    repo = payload.get("repository") or {}
    full = repo.get("full_name")
    return full, (full.split("/", 1)[1] if full else None)


def _pr_event(
    pr: dict[str, Any], repo: str | None, project: str | None, kind: str, ts: str
) -> Event:
    return Event(
        event_id=event_id(SOURCE, kind, repo, pr.get("number"), ts),
        source=SOURCE,
        kind=kind,
        ts=utc(ts),
        project=project,
        repo=repo,
        branch=(pr.get("head") or {}).get("ref"),
        meta={
            "number": pr.get("number"),
            "title": (pr.get("title") or "")[:120],
            "url": pr.get("html_url"),
            "base": (pr.get("base") or {}).get("ref"),
            "additions": pr.get("additions"),
            "deletions": pr.get("deletions"),
            "changed_files": pr.get("changed_files"),
            "draft": pr.get("draft"),
        },
    )


def parse_webhook(event_name: str, payload: dict[str, Any]) -> Iterator[Event]:
    """Normalise one delivery. Unknown events yield nothing."""
    repo, project = _repo(payload)
    now = datetime.now(tz=UTC).isoformat()
    if event_name == "push":
        ref = payload.get("ref", "")
        commits = payload.get("commits") or []
        ts = (payload.get("head_commit") or {}).get("timestamp") or now
        yield Event(
            event_id=event_id(SOURCE, "push", repo, payload.get("after")),
            source=SOURCE,
            kind="push",
            ts=utc(ts),
            project=project,
            repo=repo,
            branch=ref.replace("refs/heads/", ""),
            meta={
                "commits": len(commits),
                "forced": bool(payload.get("forced")),
                "after": str(payload.get("after", ""))[:12],
            },
        )
    elif event_name in ("create", "delete") and payload.get("ref_type") == "branch":
        kind = "branch_created" if event_name == "create" else "branch_deleted"
        yield Event(
            event_id=event_id(SOURCE, kind, repo, payload.get("ref"), now[:16]),
            source=SOURCE,
            kind=kind,
            ts=utc(now),
            project=project,
            repo=repo,
            branch=payload.get("ref"),
        )
    elif event_name == "pull_request":
        pr = payload.get("pull_request") or {}
        action = payload.get("action")
        if action == "opened":
            yield _pr_event(pr, repo, project, "pr_opened", pr.get("created_at") or now)
        elif action == "closed":
            if pr.get("merged"):
                yield _pr_event(pr, repo, project, "pr_merged", pr.get("merged_at") or now)
            else:
                yield _pr_event(pr, repo, project, "pr_closed", pr.get("closed_at") or now)
    elif event_name == "pull_request_review":
        review = payload.get("review") or {}
        pr = payload.get("pull_request") or {}
        yield Event(
            event_id=event_id(SOURCE, "review", repo, review.get("id")),
            source=SOURCE,
            kind="review",
            ts=utc(review.get("submitted_at") or now),
            project=project,
            repo=repo,
            branch=(pr.get("head") or {}).get("ref"),
            meta={"number": pr.get("number"), "state": review.get("state")},
        )
    elif event_name == "workflow_run" and payload.get("action") == "completed":
        run = payload.get("workflow_run") or {}
        yield from _workflow_run_events(run, repo, project)
    elif event_name == "deployment_status":
        st = payload.get("deployment_status") or {}
        dep = payload.get("deployment") or {}
        yield Event(
            event_id=event_id(SOURCE, "deployment_status", repo, dep.get("id"), st.get("id")),
            source=SOURCE,
            kind="deployment_status",
            ts=utc(st.get("created_at") or now),
            project=project,
            repo=repo,
            branch=dep.get("ref"),
            meta={
                "status": st.get("state"),
                "environment": dep.get("environment"),
                "url": st.get("target_url") or st.get("environment_url"),
            },
        )
    elif event_name == "release" and payload.get("action") == "published":
        rel = payload.get("release") or {}
        yield Event(
            event_id=event_id(SOURCE, "release", repo, rel.get("id")),
            source=SOURCE,
            kind="release",
            ts=utc(rel.get("published_at") or now),
            project=project,
            repo=repo,
            meta={"title": (rel.get("tag_name") or "")[:60], "url": rel.get("html_url")},
        )


def _workflow_run_events(
    run: dict[str, Any], repo: str | None, project: str | None
) -> Iterator[Event]:
    started = run.get("run_started_at") or run.get("created_at")
    finished = run.get("updated_at")
    secs = None
    if started and finished:
        secs = int((utc(finished) - utc(started)).total_seconds())
    yield Event(
        event_id=event_id(SOURCE, "workflow_run", repo, run.get("id"), run.get("run_attempt")),
        source=SOURCE,
        kind="workflow_run",
        ts=utc(finished or started or datetime.now(tz=UTC)),
        project=project,
        repo=repo,
        branch=run.get("head_branch"),
        meta={
            "name": (run.get("name") or "")[:60],
            "conclusion": run.get("conclusion"),
            "event": run.get("event"),
            "seconds": secs,
            "url": run.get("html_url"),
            "status": run.get("conclusion"),
        },
    )


# ── REST side ────────────────────────────────────────────────────────────


def _token() -> str | None:
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok
    r = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=False)
    return r.stdout.strip() or None


def client() -> httpx.Client:
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
    tok = _token()
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    return httpx.Client(base_url=API, headers=headers, timeout=30)


def _paged(
    c: httpx.Client,
    url: str,
    params: dict[str, Any] | None = None,
    key: str | None = None,
    max_pages: int = 20,
) -> Iterator[dict[str, Any]]:
    params = {"per_page": 100, **(params or {})}
    for page in range(1, max_pages + 1):
        r = c.get(url, params={**params, "page": page})
        r.raise_for_status()
        data = r.json()
        items = data[key] if key else data
        if not items:
            return
        yield from items
        if len(items) < 100:
            return


def repos(c: httpx.Client, owner: str) -> list[str]:
    # /user/repos includes private repos when authenticated as the owner.
    names = [r["full_name"] for r in _paged(c, "/user/repos", {"affiliation": "owner"})]
    if not names:
        names = [r["full_name"] for r in _paged(c, f"/users/{owner}/repos")]
    return sorted(names)


def backfill(settings: Settings, state: State, days: int = 365) -> Iterator[Event]:
    since = datetime.now(tz=UTC) - timedelta(days=days)
    with client() as c:
        for full in repos(c, settings.github_owner):
            project = full.split("/", 1)[1]
            for pr in _paged(
                c, f"/repos/{full}/pulls", {"state": "all", "sort": "updated", "direction": "desc"}
            ):
                if utc(pr["updated_at"]) < since:
                    break
                yield _pr_event(pr, full, project, "pr_opened", pr["created_at"])
                if pr.get("merged_at"):
                    yield _pr_event(pr, full, project, "pr_merged", pr["merged_at"])
                elif pr.get("closed_at"):
                    yield _pr_event(pr, full, project, "pr_closed", pr["closed_at"])
            for run in _paged(
                c,
                f"/repos/{full}/actions/runs",
                {"created": f">={since.date()}"},
                key="workflow_runs",
                max_pages=5,
            ):
                if run.get("status") == "completed":
                    yield from _workflow_run_events(run, full, project)
            for dep in _paged(c, f"/repos/{full}/deployments", max_pages=10):
                if utc(dep["created_at"]) < since:
                    continue
                for st in _paged(c, f"/repos/{full}/deployments/{dep['id']}/statuses", max_pages=1):
                    yield Event(
                        event_id=event_id(SOURCE, "deployment_status", full, dep["id"], st["id"]),
                        source=SOURCE,
                        kind="deployment_status",
                        ts=utc(st["created_at"]),
                        project=project,
                        repo=full,
                        branch=dep.get("ref"),
                        meta={
                            "status": st.get("state"),
                            "environment": dep.get("environment"),
                            "url": st.get("environment_url"),
                        },
                    )
    state.set("github_backfill_at", datetime.now(tz=UTC).isoformat())


def install_hooks(settings: Settings, url: str, *, dry_run: bool = False) -> Iterator[str]:
    secret = settings.ingest_secret
    if not secret and not dry_run:
        raise RuntimeError("PT_INGEST_SECRET must be set to install webhooks")
    with client() as c:
        for full in repos(c, settings.github_owner):
            existing = [
                h
                for h in _paged(c, f"/repos/{full}/hooks", max_pages=1)
                if (h.get("config") or {}).get("url") == url
            ]
            body = {
                "name": "web",
                "active": True,
                "events": HOOK_EVENTS,
                "config": {
                    "url": url,
                    "content_type": "json",
                    "secret": secret,
                    "insecure_ssl": "0",
                },
            }
            if dry_run:
                yield f"{full}: would {'update' if existing else 'create'} hook"
                continue
            if existing:
                r = c.patch(f"/repos/{full}/hooks/{existing[0]['id']}", json=body)
                r.raise_for_status()
                yield f"{full}: updated hook {existing[0]['id']}"
            else:
                r = c.post(f"/repos/{full}/hooks", json=body)
                r.raise_for_status()
                yield f"{full}: created hook {r.json()['id']}"
