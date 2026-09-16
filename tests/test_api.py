from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace

from fastapi.testclient import TestClient

from pt.api.app import create_app
from pt.collectors import registry
from pt.config import Settings
from pt.state import State
from pt.store.local import LocalStore
from pt.store.rollup import build


def _prepared(settings: Settings, state: State) -> Settings:
    store = LocalStore(settings.events_dir)
    for c in registry().values():
        store.append(list(c(settings, state)))
    build(settings, settings.rollups_dir)
    return settings


def test_read_routes(settings: Settings, state: State) -> None:
    cfg = replace(_prepared(settings, state), ingest_secret="s3cr3t")
    client = TestClient(create_app(cfg))
    assert client.get("/api/health").json()["ok"] is True
    t = client.get("/api/trends?grain=day&window=30").json()
    assert [r["key"] for r in t["rows"]][:3] == ["claude_sessions", "automated_sessions", "prompts"]
    assert len(t["rows"][0]["cells"]) == 30
    w = client.get("/api/trends?grain=week&window=26").json()
    assert len(w["rows"][0]["cells"]) == 26 and "growth" in w["rows"][0]
    ins = client.get("/api/insights").json()
    assert [m["key"] for m in ins["metrics"]][:2] == [
        "claude_sessions",
        "automated_sessions",
    ] and "narrative" in ins
    ov = client.get("/api/overview?week=2026-09-10").json()
    assert ov["week_start"] == "2026-09-07" and ov["kpis"]["commits"] == 2
    ag = client.get("/api/agents?days=365").json()
    assert ag["sessions"] and ag["sessions"][0]["session_id"]
    assert client.get("/api/projects?days=365").json()[0]["project"] in ("alpha", "beta")
    assert client.get("/api/projects/alpha?days=365").json()["project"] == "alpha"
    assert client.get("/api/github?days=365").json()["commits"]
    assert client.get("/api/shiplog").json()


def test_ingest_github_requires_valid_signature(settings: Settings, state: State) -> None:
    cfg = replace(_prepared(settings, state), ingest_secret="s3cr3t")
    client = TestClient(create_app(cfg))
    payload = {
        "action": "closed",
        "repository": {"full_name": "nmp-dsci/alpha"},
        "pull_request": {
            "number": 7,
            "title": "feat: x",
            "merged": True,
            "merged_at": "2026-09-11T00:00:00Z",
            "head": {"ref": "feature/x"},
            "base": {"ref": "main"},
            "html_url": "https://github.com/x/pull/7",
        },
    }
    body = json.dumps(payload).encode()
    sig = "sha256=" + hmac.new(b"s3cr3t", body, hashlib.sha256).hexdigest()
    bad = client.post(
        "/ingest/github",
        content=body,
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": "sha256=deadbeef"},
    )
    assert bad.status_code == 401
    ok = client.post(
        "/ingest/github",
        content=body,
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": sig},
    )
    assert ok.json() == {"ok": True, "event": "pull_request", "written": 1}
    again = client.post(
        "/ingest/github",
        content=body,
        headers={"X-GitHub-Event": "pull_request", "X-Hub-Signature-256": sig},
    )
    assert again.json()["written"] == 0  # idempotent on redelivery


def test_demo_mode_is_read_only_and_redacted(settings: Settings, state: State) -> None:
    cfg = replace(_prepared(settings, state), demo_mode=True, ingest_secret="s3cr3t")
    client = TestClient(create_app(cfg))
    assert client.post("/ingest/github", content=b"{}").status_code in (404, 405)
    ag = client.get("/api/agents?days=365").json()
    assert (
        ag["sessions"]
        and "session_id" not in ag["sessions"][0]
        and "branch" not in ag["sessions"][0]
    )
    text = json.dumps(client.get("/api/github?days=365").json())
    assert "feature/x" not in text
