from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, tzinfo
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pt import freshness
from pt.config import Settings
from pt.freshness import check, knowledge_readable
from pt.schema import Event, event_id
from pt.state import State
from pt.store.local import LocalStore


def _screen_event(day: date) -> Event:
    ts = datetime(day.year, day.month, day.day, 3, tzinfo=UTC)
    return Event(
        event_id=event_id("screen", "display_span_apple", ts.isoformat()),
        source="screen",
        kind="display_span_apple",
        ts=ts,
        seconds=3600.0,
        meta={"src": "knowledgeC"},
    )


def _knowledge_db(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE ZOBJECT (ZSTREAMNAME TEXT, ZVALUEINTEGER INT)")
    con.commit()
    con.close()
    return path


def test_unreadable_knowledge_db_is_a_problem(settings: Settings, tmp_path: Path) -> None:
    """Losing Full Disk Access is the one failure every scheduled job survives
    with exit 0, so the check has to call it out by itself."""
    cfg = replace(settings, knowledge_db=tmp_path / "nope" / "knowledgeC.db")
    LocalStore(cfg.events_dir).append([_screen_event(date.today())])
    _, problems = check(cfg, State(cfg.state_dir / "state.json"))
    assert len(problems) == 1 and "Full Disk Access" in problems[0]


def test_stale_screen_time_is_a_problem_even_when_readable(
    settings: Settings, tmp_path: Path
) -> None:
    """A readable store with nothing recent means the backfill is not running."""
    cfg = replace(settings, knowledge_db=_knowledge_db(tmp_path / "knowledgeC.db"))
    LocalStore(cfg.events_dir).append([_screen_event(date.today() - timedelta(days=4))])
    lines, problems = check(cfg, State(cfg.state_dir / "state.json"))
    assert knowledge_readable(cfg) is None
    assert len(problems) == 1 and "4 days behind" in problems[0]
    assert any("display_span_apple" in ln for ln in lines)


def test_fresh_screen_time_is_clean(settings: Settings, tmp_path: Path) -> None:
    cfg = replace(settings, knowledge_db=_knowledge_db(tmp_path / "knowledgeC.db"))
    LocalStore(cfg.events_dir).append([_screen_event(date.today())])
    state = State(cfg.state_dir / "state.json")
    state.set("last_full_refresh", datetime.now(UTC).date().isoformat())
    lines, problems = check(cfg, state)
    assert problems == []
    assert lines[0].endswith("(today, UTC)")


def test_last_days_uses_local_today_not_utc(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`day` is bucketed in settings.timezone (Sydney, UTC+10/+11), so lag must
    be measured against local 'today', not UTC 'today' — otherwise up to 11
    hours of every day undercounts staleness by a full day."""

    class _Frozen(datetime):
        @classmethod
        def now(cls, tz: tzinfo | None = None) -> datetime:
            base = datetime(2026, 9, 23, 22, 0, tzinfo=UTC)  # 08:00 Sydney, 9-24
            return base.astimezone(tz) if tz else base

    monkeypatch.setattr(freshness, "datetime", _Frozen)
    LocalStore(settings.events_dir).append([_screen_event(date(2026, 9, 22))])
    rows = freshness.last_days(settings)
    apple = next(r for r in rows if r.kind == "display_span_apple")
    assert apple.lag_days == 2


def test_status_command_exits_nonzero_on_a_problem(settings: Settings, tmp_path: Path) -> None:
    """`pt status` is meant to be usable from a timer, so a stale app has to
    fail the process, not just print."""
    from pt.cli import app

    env = {
        "PT_DATA_DIR": str(settings.data_dir),
        "PT_STATE_DIR": str(settings.state_dir),
        "PT_KNOWLEDGE_DB": str(tmp_path / "nope" / "knowledgeC.db"),
        "PT_TZ": settings.timezone,
    }
    LocalStore(settings.events_dir).append([_screen_event(date.today())])
    result = CliRunner().invoke(app, ["status"], env=env)
    assert result.exit_code == 1
    assert "PROBLEM" in result.output and "Full Disk Access" in result.output
