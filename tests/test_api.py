from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest
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
    assert [r["key"] for r in t["rows"]][:3] == [
        "screen_hours",
        "claude_sessions",
        "automated_sessions",
    ]
    assert len(t["rows"][0]["cells"]) == 30
    w = client.get("/api/trends?grain=week&window=26").json()
    assert len(w["rows"][0]["cells"]) == 26 and "growth" in w["rows"][0]
    ins = client.get("/api/insights").json()
    assert [m["key"] for m in ins["metrics"]][:2] == [
        "screen_hours",
        "claude_sessions",
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


def test_in_progress_periods_are_flagged_and_excluded(settings: Settings, state: State) -> None:
    """Today, and the current week, are still being lived in: they are returned
    so the strip can draw them, but they must not move a total or a growth %."""
    cfg = _prepared(settings, state)
    client = TestClient(create_app(cfg))

    day = client.get("/api/trends?grain=day&window=30").json()
    assert day["complete_through"] == (date.today() - timedelta(days=1)).isoformat()
    for row in day["rows"]:
        cells = row["cells"]
        assert [c["d"] for c in cells if not c["done"]] == [date.today().isoformat()]
        assert row["periods"] == len(cells) - 1
        assert row["total"] == pytest.approx(sum(c["v"] for c in cells if c["done"]))


def test_week_grain_is_rolling_seven_whole_days(settings: Settings, state: State) -> None:
    """Weeks are 7-day blocks anchored on the last complete day and recomputed
    daily — never a calendar week that is one day old on a Monday."""
    client = TestClient(create_app(_prepared(settings, state)))
    week = client.get("/api/trends?grain=week&window=26").json()
    yesterday = date.today() - timedelta(days=1)
    assert week["complete_through"] == yesterday.isoformat()
    for row in week["rows"]:
        cells = row["cells"]
        assert len(cells) == 26 and row["periods"] == 26
        assert all(c["done"] for c in cells)
        # Every block is exactly seven days long and they tile without gaps.
        for c in cells:
            assert (date.fromisoformat(c["end"]) - date.fromisoformat(c["d"])).days == 6
        for a, b in zip(cells[:-1], cells[1:], strict=True):
            assert date.fromisoformat(b["d"]) - date.fromisoformat(a["end"]) == timedelta(days=1)
        assert cells[-1]["end"] == yesterday.isoformat()
        assert row["total"] == pytest.approx(sum(c["v"] for c in cells))
        # The tiles cover the same seven days as the last block.
        assert len(row["spark"]) == 26


def test_insights_window_ends_yesterday(settings: Settings, state: State) -> None:
    """A part-day against seven whole ones reads as a collapse, so the rolling
    window stops at the last complete day."""
    cfg = _prepared(settings, state)
    ins = TestClient(create_app(cfg)).get("/api/insights").json()
    assert ins["end"] == (date.today() - timedelta(days=1)).isoformat()
    assert ins["start"] == (date.today() - timedelta(days=7)).isoformat()
    assert ins["prior_end"] == (date.today() - timedelta(days=8)).isoformat()
    assert ins["as_of"] == date.today().isoformat()


def test_screen_hours(settings: Settings, state: State, tmp_path: Path) -> None:
    """Display spans roll up as hours per local day."""
    today = date.today()
    log = tmp_path / "pmset.log"
    log.write_text(
        "\n".join(
            f"{d} {t} +0000 Notification\tDisplay is turned {onoff}"
            for d, t, onoff in [
                ((today - timedelta(days=2)).isoformat(), "01:00:00", "on"),
                ((today - timedelta(days=2)).isoformat(), "03:00:00", "off"),
                ((today - timedelta(days=1)).isoformat(), "01:00:00", "on"),
                ((today - timedelta(days=1)).isoformat(), "07:00:00", "off"),
            ]
        )
    )
    cfg = replace(_prepared(replace(settings, pmset_log=log), state), pmset_log=log)
    rows = TestClient(create_app(cfg)).get("/api/trends?grain=day&window=7").json()["rows"]
    hours = {r["key"]: r for r in rows}["screen_hours"]
    # 2h and 6h of display-on, each on its own local day, both complete.
    assert round(hours["total"], 2) == 8.0
    assert [round(c["v"], 2) for c in hours["cells"][-3:]] == [2.0, 6.0, 0.0]
