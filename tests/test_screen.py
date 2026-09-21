"""Screen time collector: pmset spans, midnight splitting, and the knowledgeC
backfill. `pmset -g log` is a text format Apple owes us nothing about, so the
fixture pins the shape we parse today."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pt.collectors.screen import backfill, collect, spans, split_days
from pt.config import Settings
from pt.state import State

LOG = (Path(__file__).parent / "fixtures" / "screen" / "pmset.log").read_text()


def test_spans_pairs_on_and_off_and_ignores_dark_wake() -> None:
    got = [(a.isoformat(), (b - a).total_seconds()) for a, b in spans(LOG)]
    assert got == [
        ("2026-09-13T22:15:00+00:00", 3600.0),  # 08:15 → 09:15 local
        # 10:30 → 10:35 is a dark wake — the screen was never lit: dropped.
        ("2026-09-14T01:00:00+00:00", 3600.0),  # a repeated "on" keeps the first
        ("2026-09-14T13:50:00+00:00", 1800.0),  # crosses local midnight
        # 09-15 09:00 → 09-16 09:00 is 24h, so an "off" was missed: dropped.
        # The final "on" at 09-16 10:00 never closes, so it is not emitted until
        # we see its "off" — re-reading the log cannot change a duration we wrote.
    ]


def test_absurd_spans_are_dropped() -> None:
    """A missed "off" would otherwise invent a 24-hour day."""
    long_day = [a for a, b in spans(LOG) if (b - a) > timedelta(hours=16)]
    assert long_day == []


def test_split_days_cuts_at_local_midnight() -> None:
    start = datetime(2026, 9, 14, 13, 50, tzinfo=UTC)  # 23:50 Sydney
    pieces = list(split_days(start, start + timedelta(minutes=30), "Australia/Sydney"))
    assert [s for _, s in pieces] == [600.0, 1200.0]  # 10 min, then 20 min
    assert pieces[1][0] == datetime(2026, 9, 14, 14, 0, tzinfo=UTC)


def test_collect_is_idempotent(settings: Settings, state: State, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr("pt.collectors.screen._pmset_log", lambda: LOG)
    first = list(collect(settings, state))
    again = list(collect(settings, state))
    assert first and [e.event_id for e in first] == [e.event_id for e in again]
    assert {e.source for e in first} == {"screen"}
    assert all(e.seconds and e.seconds > 0 for e in first)
    # Privacy: a span is a start and a duration, nothing else.
    assert all(set(e.meta) <= {"src", "split"} for e in first)


def test_backfill_reads_backlit_spans(settings: Settings, state: State, tmp_path: Path) -> None:
    db = tmp_path / "knowledgeC.db"
    con = sqlite3.connect(db)
    con.execute(
        "CREATE TABLE ZOBJECT (ZSTREAMNAME TEXT, ZVALUEINTEGER INT, ZSTARTDATE REAL, ZENDDATE REAL)"
    )
    mac = datetime(2001, 1, 1, tzinfo=UTC)
    recent = (datetime.now(UTC) - timedelta(days=2) - mac).total_seconds()
    old = (datetime.now(UTC) - timedelta(days=90) - mac).total_seconds()
    con.executemany(
        "INSERT INTO ZOBJECT VALUES (?, ?, ?, ?)",
        [
            ("/display/isBacklit", 1, recent, recent + 3600),
            ("/display/isBacklit", 0, recent, recent + 60),  # screen off: skipped
            ("/app/inFocus", 1, recent, recent + 60),  # another stream: skipped
            ("/display/isBacklit", 1, old, old + 3600),  # outside the window
        ],
    )
    con.commit()
    con.close()
    cfg = Settings(**{**settings.__dict__, "knowledge_db": db})
    events = list(backfill(cfg, state, days=30))
    assert len(events) == 1 and events[0].seconds == 3600.0
    assert events[0].meta["src"] == "knowledgeC"


def test_backfill_without_access_explains_itself(settings: Settings, state: State) -> None:
    cfg = Settings(**{**settings.__dict__, "knowledge_db": Path("/nope/knowledgeC.db")})
    with pytest.raises(PermissionError, match="Full Disk Access"):
        list(backfill(cfg, state, days=30))
