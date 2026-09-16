"""Append-only local event store.

Layout: `data/events/<source>/<YYYY-MM-DD>.jsonl`, one event per line, bucketed
by the event's UTC date. Appends are deduplicated on `event_id` so collectors
can be re-run freely. S3 mirrors this layout byte-for-byte (`store/s3.py`).
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Iterator
from pathlib import Path

from pt.schema import Event


class LocalStore:
    def __init__(self, events_dir: Path) -> None:
        self.events_dir = events_dir

    def _file(self, ev: Event) -> Path:
        return self.events_dir / ev.source / f"{ev.ts.date().isoformat()}.jsonl"

    @staticmethod
    def _ids_in(path: Path) -> set[str]:
        ids: set[str] = set()
        if not path.exists():
            return ids
        with path.open() as fh:
            for line in fh:
                try:
                    ids.add(json.loads(line)["event_id"])
                except (json.JSONDecodeError, KeyError):
                    continue
        return ids

    def append(self, events: Iterable[Event]) -> int:
        """Write events not already present. Returns the number written."""
        by_file: dict[Path, list[Event]] = defaultdict(list)
        for ev in events:
            by_file[self._file(ev)].append(ev)
        written = 0
        for path, evs in by_file.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            seen = self._ids_in(path)
            with path.open("a") as fh:
                for ev in evs:
                    if ev.event_id in seen:
                        continue
                    fh.write(ev.to_json() + "\n")
                    seen.add(ev.event_id)
                    written += 1
        return written

    def files(self, source: str | None = None) -> list[Path]:
        base = self.events_dir / source if source else self.events_dir
        return sorted(base.glob("**/*.jsonl")) if base.exists() else []

    def read(self, source: str | None = None) -> Iterator[Event]:
        for path in self.files(source):
            with path.open() as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        yield Event.model_validate_json(line)

    def count(self, source: str | None = None) -> int:
        return sum(1 for _ in self.read(source))
