"""How current is the data behind the app?

The collectors are incremental and quiet by design: a source that stops
producing looks exactly like a source with nothing to say. That is fine for
most of them, but not for screen time, whose only reader (`knowledgeC.db`)
needs Full Disk Access — a permission the scheduled LaunchAgent can lose, or
never have, while every job keeps exiting 0 and the metric silently flatlines.

`check()` turns that into something a human or a timer can see.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from pt.config import Settings
from pt.state import State
from pt.store.rollup import connect

# Screen time is read from Apple's store, which only ever holds the recent
# past: a lag of more than a day means the reader has stopped working, not
# that the Mac went unused (an unused Mac still records the days around it).
SCREEN_MAX_LAG_DAYS = 1

# The LaunchAgents that keep the data current: one collects every 5 minutes,
# the other rebuilds everything once the UTC day turns. Nothing else notices
# when they stop, and they have stopped before — on 2026-09-24 both were
# unloaded and every source quietly went two days stale.
AGENTS = ("com.nmp-dsci.pt-collect", "com.nmp-dsci.pt-refresh")


def _launchctl_labels() -> set[str] | None:
    """Labels launchd currently has loaded for this user, or None when that
    cannot be established (not macOS, or launchctl missing or unhappy)."""
    if sys.platform != "darwin" or not shutil.which("launchctl"):
        return None
    try:
        out = subprocess.run(
            ["launchctl", "list"], capture_output=True, text=True, timeout=20, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return {line.split("\t")[-1].strip() for line in out.stdout.splitlines()[1:]}


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
    utc_today = datetime.now(UTC).date()
    today = utc_today.isoformat()
    stamp = state.get("last_full_refresh")
    lines = [
        f"last full refresh   {stamp or 'never'}"
        + ("  (today, UTC)" if stamp == today else f"  (today is {today} UTC)"),
        "",
    ]
    problems: list[str] = []
    # The refresh timer polls every 30 minutes and only acts once the UTC date
    # turns, so yesterday's stamp is normal for the first half-hour of a new
    # day. Anything older means the timer is not running at all.
    if stamp is None or date.fromisoformat(stamp) < utc_today - timedelta(days=1):
        problems.append(
            f"The daily full refresh last ran {stamp or 'never'} (today is {today} UTC) — "
            "the pt-refresh LaunchAgent is not running."
        )
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
    loaded = _launchctl_labels()
    if loaded is None:
        lines.append("launch agents       not checked (launchctl unavailable)")
    else:
        missing = [a for a in AGENTS if a not in loaded]
        state_word = "all loaded" if not missing else f"MISSING {', '.join(missing)}"
        lines.append(f"launch agents       {state_word}")
        if missing:
            problems.append(
                f"{len(missing)} of {len(AGENTS)} LaunchAgents are not loaded, so nothing is "
                "collecting: re-run `scripts/install_launchd.sh`."
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
