from __future__ import annotations

import sqlite3
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import Self
from zoneinfo import ZoneInfo

import pytest
from typer.testing import CliRunner

from pt import freshness
from pt.config import Settings
from pt.freshness import check, knowledge_readable
from pt.schema import Event, event_id
from pt.state import State
from pt.store.local import LocalStore


def _today(settings: Settings) -> date:
    """Today in the configured zone — the same clock `freshness` reads.

    Not `date.today()`: that is the *machine's* local date, which differs from
    the configured zone's for a third of every day on a UTC CI runner, and
    would put the lag arithmetic in these tests a day out from the code's."""
    return datetime.now(ZoneInfo(settings.timezone)).date()


def _screen_event(settings: Settings, day: date) -> Event:
    # Local noon, so the event lands on `day` in the configured zone whatever
    # that zone's offset is.
    ts = datetime.combine(day, time(12), tzinfo=ZoneInfo(settings.timezone)).astimezone(UTC)
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


@pytest.fixture(autouse=True)
def _healthy_agents_and_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the two checks that read the host: whether this laptop's LaunchAgents
    happen to be loaded is not what any other test in this file is about."""
    monkeypatch.setattr(freshness, "_launchctl_labels", lambda: set(freshness.AGENTS))


def _fresh_state(settings: Settings) -> State:
    state = State(settings.state_dir / "state.json")
    state.set("last_full_refresh", datetime.now(UTC).date().isoformat())
    return state


def test_unloaded_agents_are_a_problem(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both agents were once found silently unloaded, which stops every source
    at once. Nothing reported it, so the check now does."""
    monkeypatch.setattr(freshness, "_launchctl_labels", lambda: {"com.apple.something.else"})
    cfg = replace(settings, knowledge_db=_knowledge_db(tmp_path / "knowledgeC.db"))
    LocalStore(cfg.events_dir).append([_screen_event(cfg, _today(cfg))])
    lines, problems = check(cfg, _fresh_state(cfg))
    assert len(problems) == 1 and "2 of 2 LaunchAgents are not loaded" in problems[0]
    assert any("MISSING" in ln for ln in lines)


def test_launchctl_unavailable_is_not_a_problem(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Off macOS — in CI, or in the demo container — there are no agents to
    check, and saying so is not the same as reporting a fault."""
    monkeypatch.setattr(freshness, "_launchctl_labels", lambda: None)
    cfg = replace(settings, knowledge_db=_knowledge_db(tmp_path / "knowledgeC.db"))
    LocalStore(cfg.events_dir).append([_screen_event(cfg, _today(cfg))])
    lines, problems = check(cfg, _fresh_state(cfg))
    assert problems == []
    assert any("not checked" in ln for ln in lines)


def test_a_stalled_daily_refresh_is_a_problem(settings: Settings, tmp_path: Path) -> None:
    """A stamp older than yesterday means the refresh timer is not running;
    yesterday's is normal, because the timer only acts once the UTC date turns
    and polls every 30 minutes."""
    cfg = replace(settings, knowledge_db=_knowledge_db(tmp_path / "knowledgeC.db"))
    LocalStore(cfg.events_dir).append([_screen_event(cfg, _today(cfg))])
    state = State(cfg.state_dir / "state.json")
    utc_today = datetime.now(UTC).date()

    state.set("last_full_refresh", (utc_today - timedelta(days=1)).isoformat())
    assert check(cfg, state)[1] == []

    state.set("last_full_refresh", (utc_today - timedelta(days=2)).isoformat())
    _, problems = check(cfg, state)
    assert len(problems) == 1 and "pt-refresh LaunchAgent is not running" in problems[0]


def test_unreadable_knowledge_db_is_a_problem(settings: Settings, tmp_path: Path) -> None:
    """Losing Full Disk Access is the one failure every scheduled job survives
    with exit 0, so the check has to call it out by itself."""
    cfg = replace(settings, knowledge_db=tmp_path / "nope" / "knowledgeC.db")
    LocalStore(cfg.events_dir).append([_screen_event(cfg, _today(cfg))])
    _, problems = check(cfg, _fresh_state(cfg))
    assert len(problems) == 1 and "Full Disk Access" in problems[0]


def test_stale_screen_time_is_a_problem_even_when_readable(
    settings: Settings, tmp_path: Path
) -> None:
    """A readable store with nothing recent means the backfill is not running."""
    cfg = replace(settings, knowledge_db=_knowledge_db(tmp_path / "knowledgeC.db"))
    LocalStore(cfg.events_dir).append([_screen_event(cfg, _today(cfg) - timedelta(days=4))])
    lines, problems = check(cfg, _fresh_state(cfg))
    assert knowledge_readable(cfg) is None
    assert len(problems) == 1 and "4 days behind" in problems[0]
    assert any("display_span_apple" in ln for ln in lines)


def test_fresh_screen_time_is_clean(settings: Settings, tmp_path: Path) -> None:
    cfg = replace(settings, knowledge_db=_knowledge_db(tmp_path / "knowledgeC.db"))
    LocalStore(cfg.events_dir).append([_screen_event(cfg, _today(cfg))])
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
        def now(cls, tz: tzinfo | None = None) -> Self:
            base = datetime(2026, 9, 23, 22, 0, tzinfo=UTC)  # 08:00 Sydney, 9-24
            moment = base.astimezone(tz) if tz else base
            return cls.fromtimestamp(moment.timestamp(), tz=moment.tzinfo)

    monkeypatch.setattr(freshness, "datetime", _Frozen)
    LocalStore(settings.events_dir).append([_screen_event(settings, date(2026, 9, 22))])
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
    LocalStore(settings.events_dir).append([_screen_event(settings, _today(settings))])
    result = CliRunner().invoke(app, ["status"], env=env)
    assert result.exit_code == 1
    assert "PROBLEM" in result.output and "Full Disk Access" in result.output
