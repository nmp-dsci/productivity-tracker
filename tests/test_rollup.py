from __future__ import annotations

import duckdb

from pt.collectors import registry
from pt.config import Settings
from pt.state import State
from pt.store.local import LocalStore
from pt.store.rollup import build


def test_rollups_reproduce_hand_counts(settings: Settings, state: State) -> None:
    store = LocalStore(settings.events_dir)
    for c in registry().values():
        store.append(list(c(settings, state)))
    rows = build(settings, settings.rollups_dir)
    assert set(rows) == {"daily", "sessions", "shiplog"} and rows["daily"] > 0
    con = duckdb.connect()
    daily = f"'{settings.rollups_dir / 'daily.parquet'}'"
    out = con.execute(
        f"SELECT sum(tok_out) FROM {daily} WHERE source='claude_code' AND kind='assistant_message'"
    ).fetchone()
    assert (
        out and out[0] == 500 + 50 + 20 + 900
    )  # msg_1 counted once despite three lines; sess-3 adds 3×300
    day = con.execute(
        f"SELECT day FROM {daily} WHERE source='claude_code' AND kind='assistant_message' LIMIT 1"
    ).fetchone()
    assert day and str(day[0]) == "2026-09-10"  # 02:00Z → 12:00 Sydney, same day
    sess = con.execute(
        f"SELECT cls, messages FROM '{settings.rollups_dir / 'sessions.parquet'}' WHERE session_id='sess-1'"
    ).fetchone()
    assert (
        sess and sess[0] == "evals" and sess[1] == 3
    )  # 2 eval votes (tests/ path + pytest) vs 1 building
    ship = con.execute(
        f"SELECT kind, title FROM '{settings.rollups_dir / 'shiplog.parquet'}' ORDER BY kind"
    ).fetchall()
    assert ("page_created", "Alpha plan") in ship and ("run", "r1") in ship
