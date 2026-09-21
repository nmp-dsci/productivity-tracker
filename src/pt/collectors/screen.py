"""Screen time — hours the display was on, the same number macOS Screen Time
shows for this Mac.

Two readers, one event kind:

- `collect()` parses `pmset -g log`, which records every "Display is turned
  on/off" transition. It needs no permissions at all, but Apple keeps only
  about a week of it, so it runs on the ordinary 5-minute collect tick.
- `backfill()` (kind `display_span_apple`) reads `/display/isBacklit` out of Apple's own Screen Time store
  (`~/Library/Application Support/Knowledge/knowledgeC.db`) for roughly a
  month of history. That file is TCC-protected: the *running process* needs
  Full Disk Access, and without it we log a clear line and yield nothing.

Both emit spans carrying a start and a duration — no app names, no window
titles, no URLs — split at local midnight so every event belongs to exactly
one local day. The two overlap on the days they both cover, so they are stored
under different kinds and `screen_hours` takes the larger of the two per day
instead of adding them up.
"""

from __future__ import annotations

import re
import sqlite3
import subprocess
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pt.config import Settings
from pt.schema import Event, Source, event_id
from pt.state import State

SOURCE: Source = "screen"
# Live record (pmset) and Apple's backfill measure the same hours, so they get
# distinct kinds and the rollup takes one per day rather than summing both.
KIND = "display_span"
KIND_BACKFILL = "display_span_apple"

# 2026-09-21 08:06:47 +1000 Notification   Display is turned on
_LINE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) ([+-]\d{4})\s+(\S+)\s+(.*?)\s*$",
)
_ON = "Display is turned on"
_OFF = "Display is turned off"
# A dark wake is the machine servicing a backup or a push with the screen
# dark; pmset prints it in the kind column. It is not time at the keyboard.
_DARK = re.compile(r"dark\s*wake", re.I)
# The longest plausible single sitting. Anything longer means we missed an
# "off" (log rolled, machine hard-crashed) and would invent a 30-hour day.
MAX_SPAN = timedelta(hours=16)


def _pmset_log() -> str:
    try:
        out = subprocess.run(
            ["pmset", "-g", "log"], capture_output=True, text=True, timeout=120, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout


def spans(log: str) -> list[tuple[datetime, datetime]]:
    """Closed display-on spans, oldest first.

    Only spans whose end we have actually seen are returned: the session in
    progress is emitted once it closes, so re-reading the same log never
    changes a duration we already wrote."""
    out: list[tuple[datetime, datetime]] = []
    start: datetime | None = None
    for line in log.splitlines():
        m = _LINE.match(line)
        if not m:
            continue
        stamp, offset, kind, msg = m.groups()
        if _DARK.search(kind) or _DARK.search(msg):
            continue
        if not (msg.startswith(_ON) or msg.startswith(_OFF)):
            continue
        ts = datetime.strptime(f"{stamp} {offset}", "%Y-%m-%d %H:%M:%S %z").astimezone(UTC)
        if msg.startswith(_ON):
            # Two "on"s in a row: keep the earlier, the display never went off.
            start = start or ts
        elif start is not None:
            if timedelta() < ts - start <= MAX_SPAN:
                out.append((start, ts))
            start = None
    return out


def split_days(start: datetime, end: datetime, tz: str) -> Iterator[tuple[datetime, float]]:
    """Cut a span at local midnight so each piece sits in one local day."""
    zone = ZoneInfo(tz)
    cur = start
    while cur < end:
        midnight = (cur.astimezone(zone) + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        stop = min(end, midnight.astimezone(UTC))
        yield cur, (stop - cur).total_seconds()
        cur = stop


def _events(
    pairs: list[tuple[datetime, datetime]], tz: str, src: str, kind: str = KIND
) -> Iterator[Event]:
    for start, end in pairs:
        pieces = list(split_days(start, end, tz))
        for piece_start, seconds in pieces:
            if seconds <= 0:
                continue
            yield Event(
                event_id=event_id(SOURCE, kind, piece_start.isoformat()),
                source=SOURCE,
                kind=kind,
                ts=piece_start,
                seconds=round(seconds, 1),
                cls="unknown",
                meta={"src": src} | ({"split": True} if len(pieces) > 1 else {}),
            )


def collect(settings: Settings, state: State) -> Iterator[Event]:
    """Display spans from `pmset -g log` (about 7 days of history)."""
    log = settings.pmset_log.read_text() if settings.pmset_log else _pmset_log()
    yield from _events(spans(log), settings.timezone, "pmset")


# ── knowledgeC.db (Apple's own Screen Time store) ─────────────────────────
# Mac absolute time is seconds since 2001-01-01 UTC.
_MAC_EPOCH = datetime(2001, 1, 1, tzinfo=UTC)
_KNOWLEDGE_SQL = """
SELECT ZSTARTDATE, ZENDDATE FROM ZOBJECT
WHERE ZSTREAMNAME = '/display/isBacklit' AND ZVALUEINTEGER = 1
  AND ZSTARTDATE IS NOT NULL AND ZENDDATE IS NOT NULL
ORDER BY ZSTARTDATE
"""


def knowledge_spans(db: Path, since: datetime) -> list[tuple[datetime, datetime]]:
    """Backlit spans from knowledgeC. Raises sqlite3.Error without Full Disk
    Access — the caller turns that into a readable message."""
    con = sqlite3.connect(f"file:{db}?mode=ro&immutable=1", uri=True)
    try:
        rows = con.execute(_KNOWLEDGE_SQL).fetchall()
    finally:
        con.close()
    out = []
    for z_start, z_end in rows:
        start = _MAC_EPOCH + timedelta(seconds=float(z_start))
        end = _MAC_EPOCH + timedelta(seconds=float(z_end))
        if start >= since and timedelta() < end - start <= MAX_SPAN:
            out.append((start, end))
    return out


def backfill(settings: Settings, state: State, days: int = 45) -> Iterator[Event]:
    """History from Apple's store — the default reading for any day it covers.

    Apple keeps about 30 days (measured 2026-09-21: `/display/isBacklit` went
    back 29 days), so asking for more is harmless and costs nothing; our own
    event store is the only record of anything older. Raises PermissionError
    when the process has no Full Disk Access."""
    db = settings.knowledge_db
    since = datetime.now(UTC) - timedelta(days=days)
    try:
        pairs = knowledge_spans(db, since)
    except sqlite3.Error as exc:  # denied, missing, or a schema we don't know
        raise PermissionError(
            f"cannot read {db}: {exc}. Grant Full Disk Access to this terminal in "
            "System Settings → Privacy & Security → Full Disk Access, then re-run."
        ) from exc
    yield from _events(pairs, settings.timezone, "knowledgeC", KIND_BACKFILL)
