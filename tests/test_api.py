from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

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
        # The sparkline caption promises 26 rolling blocks regardless of grain.
        assert len(row["spark"]) == 26


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
    """Apple's backlit spans roll up as hours in the right local day."""
    import sqlite3
    from dataclasses import replace as _replace

    from pt.collectors.screen import backfill as screen_backfill

    db = tmp_path / "knowledgeC.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE ZOBJECT (ZSTREAMNAME TEXT, ZVALUEINTEGER INT, ZSTARTDATE REAL, ZENDDATE REAL)"
    )
    mac = datetime(2001, 1, 1, tzinfo=UTC)
    # Anchored at 09:00 *local*, not at "now minus N days": a span that starts
    # at the current time of day runs into the next local day whenever the test
    # happens to run late enough, and the part that lands on today is correctly
    # dropped as an in-progress period — which made this assertion depend on
    # the wall clock. 09:00 + 6h stays inside one local day at every offset.
    zone = ZoneInfo(settings.timezone)
    today = datetime.now(zone).date()
    two, one = (
        datetime.combine(today - timedelta(days=n), time(9), tzinfo=zone).astimezone(UTC)
        for n in (2, 1)
    )
    con.executemany(
        "INSERT INTO ZOBJECT VALUES ('/display/isBacklit', 1, ?, ?)",
        [
            ((two - mac).total_seconds(), (two - mac).total_seconds() + 7200),
            ((one - mac).total_seconds(), (one - mac).total_seconds() + 21600),
        ],
    )
    con.commit()
    con.close()

    cfg = _replace(_prepared(settings, state), knowledge_db=db)
    LocalStore(cfg.events_dir).append(list(screen_backfill(cfg, state)))
    build(cfg, cfg.rollups_dir)
    rows = TestClient(create_app(cfg)).get("/api/trends?grain=day&window=7").json()["rows"]
    hours = {r["key"]: r for r in rows}["screen_hours"]
    # 2h and 6h, each wholly inside its own complete local day.
    assert round(hours["total"], 2) == 8.0


def test_screen_hours_come_only_from_knowledgec(
    settings: Settings, state: State, tmp_path: Path
) -> None:
    """pmset and knowledgeC are two readings of the same hours on different
    scales. The metric is Apple's alone — pmset is collected but never counted,
    so the row can never mix the two."""
    from pt.collectors.screen import KIND, KIND_BACKFILL
    from pt.schema import Event, event_id

    day, other = date.today() - timedelta(days=2), date.today() - timedelta(days=3)
    cfg = _prepared(settings, state)
    LocalStore(cfg.events_dir).append(
        [
            Event(
                event_id=event_id("screen", kind, f"{d}T01:00:00+00:00"),
                source="screen",
                kind=kind,
                ts=datetime(d.year, d.month, d.day, 1, tzinfo=UTC),
                seconds=secs,
                meta={"src": src},
            )
            for d, kind, secs, src in [
                (day, KIND, 7200.0, "pmset"),  # both cover this day
                (day, KIND_BACKFILL, 3600.0, "knowledgeC"),
                (other, KIND, 1800.0, "pmset"),  # pmset only
            ]
        ]
    )
    build(cfg, cfg.rollups_dir)
    rows = TestClient(create_app(cfg)).get("/api/trends?grain=day&window=7").json()["rows"]
    cells = {c["d"]: c["v"] for c in {r["key"]: r for r in rows}["screen_hours"]["cells"]}
    assert cells[day.isoformat()] == 1.0  # Apple's 1h, not 3h and not the 2h sum
    assert cells[other.isoformat()] == 0.0  # pmset alone does not make a number


def test_refresh_runs_once_per_utc_day(settings: Settings, state: State) -> None:
    """The refresh is safe to call from a frequent timer: it rebuilds on the
    first call of a UTC day and no-ops for the rest of that day."""
    from datetime import datetime

    from typer.testing import CliRunner

    from pt.cli import app

    runner = CliRunner()
    env = {
        "PT_DATA_DIR": str(settings.data_dir),
        "PT_STATE_DIR": str(settings.state_dir),
        "PT_CLAUDE_DIR": str(settings.claude_dir),
        "PT_CODEX_DIR": str(settings.codex_dir),
        "PT_NOMISTAKES_DIR": str(settings.nomistakes_dir),
        "PT_PMSET_LOG": str(settings.pmset_log),
        "PT_KNOWLEDGE_DB": "/nope/knowledgeC.db",
        "PT_REPO_ROOTS": ":".join(str(r) for r in settings.repo_roots),
        "PT_TZ": settings.timezone,
    }
    first = runner.invoke(app, ["refresh", "--no-remote"], env=env)
    assert first.exit_code == 0, first.output
    assert "refresh" in first.output and "new events" in first.output
    # Apple's store is unreadable here: that is a warning, never a failure.
    assert "screen backfill skipped" in first.output

    again = runner.invoke(app, ["refresh", "--no-remote"], env=env)
    assert again.exit_code == 0
    today = datetime.now(UTC).date().isoformat()
    assert f"already done for {today}" in again.output

    forced = runner.invoke(app, ["refresh", "--no-remote", "--force"], env=env)
    assert forced.exit_code == 0 and "already done" not in forced.output
