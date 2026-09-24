"""How current is the data behind the app?

The collectors are incremental and quiet by design: a source that stops
producing looks exactly like a source with nothing to say. That is fine for
most of them, but not for screen time, whose only reader (`knowledgeC.db`)
needs Full Disk Access — a permission the scheduled LaunchAgent can lose, or
never have, while every job keeps exiting 0 and the metric silently flatlines.

`check()` turns that into something a human or a timer can see.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from pt.config import Settings
from pt.state import State
from pt.store.rollup import connect

# Screen time is read from Apple's store, which only ever holds the recent
# past: a lag of more than a day means the reader has stopped working, not
# that the Mac went unused (an unused Mac still records the days around it).
SCREEN_MAX_LAG_DAYS = 1


@dataclass(frozen=True)
class Row:
    source: str
    kind: str
    last_day: date
    lag_days: int


def last_days(settings: Settings) -> list[Row]:
    """Most recent local day carrying an event, per source and kind."""
    con = connect(settings)
    try:
        rows = con.execute(
            "SELECT source, kind, max(day) FROM events GROUP BY 1, 2 ORDER BY 1, 2"
        ).fetchall()
    finally:
        con.close()
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    return [Row(s, k, d, (today - d).days) for s, k, d in rows if d is not None]


def knowledge_readable(settings: Settings) -> str | None:
    """None when Apple's Screen Time store can be read, else why it cannot."""
    try:
        con = sqlite3.connect(f"file:{settings.knowledge_db}?mode=ro&immutable=1", uri=True)
        try:
            con.execute("SELECT 1 FROM ZOBJECT LIMIT 1").fetchone()
        finally:
            con.close()
    except sqlite3.Error as exc:
        return str(exc)
    return None


def check(settings: Settings, state: State) -> tuple[list[str], list[str]]:
    """(lines to print, problems). A problem means the app is showing stale
    numbers and a person has to do something about it."""
    today = datetime.now(UTC).date().isoformat()
    stamp = state.get("last_full_refresh")
    lines = [
        f"last full refresh   {stamp or 'never'}"
        + ("  (today, UTC)" if stamp == today else f"  (today is {today} UTC)"),
        "",
    ]
    problems: list[str] = []
    rows = last_days(settings)
    labels = {r: f"{r.source}/{r.kind}" for r in rows}
    width = max((len(v) for v in labels.values()), default=20)
    for r in rows:
        lines.append(f"  {labels[r]:<{width}}  {r.last_day}  ({r.lag_days}d ago)")

    lines.append("")
    why = knowledge_readable(settings)
    if why is None:
        lines.append("screen time         knowledgeC.db readable")
    else:
        lines.append(f"screen time         CANNOT read {settings.knowledge_db}: {why}")
        problems.append(
            "No Full Disk Access for this process, so screen time cannot update. "
            "Grant it in System Settings → Privacy & Security → Full Disk Access."
        )
    apple = next((r for r in rows if r.kind == "display_span_apple"), None)
    if apple is None:
        problems.append("No screen-time events at all — run `pt screen-backfill`.")
    elif apple.lag_days > SCREEN_MAX_LAG_DAYS:
        problems.append(
            f"Screen time is {apple.lag_days} days behind (last {apple.last_day}); "
            "the scheduled backfill is not reaching knowledgeC.db."
        )
    return lines, problems
