"""Lavish pages: every `<repo>/.lavish/sNN_*.html` is a review artefact —
a proxy for design/plan effort. mtime is the event time; a changed mtime
is a `page_updated` event (the id includes the mtime, so history is kept)."""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime

from pt.collectors._util import repos_under
from pt.config import Settings
from pt.schema import Event, Source, event_id
from pt.state import State

SOURCE: Source = "lavish"
_TITLE = re.compile(r"<title>(.*?)</title>", re.I | re.S)
_SEQ = re.compile(r"^s(\d{2,})_")


def collect(settings: Settings, state: State) -> Iterator[Event]:
    seen: dict[str, float] = state.get("lavish_seen", {})
    for repo in repos_under(settings.repo_roots):
        lav = repo / ".lavish"
        if not lav.is_dir():
            continue
        for page in sorted(lav.glob("*.html")):
            mtime = page.stat().st_mtime
            key = str(page)
            prev = seen.get(key)
            if prev is not None and prev >= mtime:
                continue
            head = page.read_text(errors="replace")[:8000]
            m = _TITLE.search(head)
            title = re.sub(r"\s+", " ", m.group(1)).strip()[:120] if m else page.stem
            seq = _SEQ.match(page.name)
            yield Event(
                event_id=event_id(SOURCE, key, int(mtime)),
                source=SOURCE,
                kind="page_created" if prev is None else "page_updated",
                ts=datetime.fromtimestamp(mtime, tz=UTC),
                project=repo.name,
                cls="writing",
                meta={
                    "file": page.name,
                    "title": title,
                    "bytes": page.stat().st_size,
                    "seq": int(seq.group(1)) if seq else None,
                },
            )
            seen[key] = mtime
    state.set("lavish_seen", seen)
