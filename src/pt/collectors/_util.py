from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

from pt.state import State


def tail_jsonl(path: Path, state: State, collector: str) -> Iterator[dict[str, Any]]:
    """Yield JSON objects appended to `path` since the last run.

    Offsets are byte positions in `state`; a file that shrank (rotated or
    rewritten) is re-read from the start. Malformed lines are skipped, and a
    trailing partial line (a writer mid-append) is left for the next run.
    """
    key = str(path)
    offset = state.offsets(collector).get(key, 0)
    size = path.stat().st_size
    if size < offset:
        offset = 0
    if size == offset:
        return
    with path.open("rb") as fh:
        fh.seek(offset)
        for raw in fh:
            if not raw.endswith(b"\n"):
                break
            offset += len(raw)
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                continue
    state.set_offset(collector, key, offset)


def tail_lines(path: Path, state: State, collector: str) -> Iterator[str]:
    """Like `tail_jsonl` but yields raw text lines (for non-JSON logs)."""
    key = str(path)
    offset = state.offsets(collector).get(key, 0)
    size = path.stat().st_size
    if size < offset:
        offset = 0
    if size == offset:
        return
    with path.open("rb") as fh:
        fh.seek(offset)
        for raw in fh:
            if not raw.endswith(b"\n"):
                break
            offset += len(raw)
            yield raw.decode("utf-8", errors="replace").rstrip("\n")
    state.set_offset(collector, key, offset)


def repos_under(roots: Iterable[Path]) -> list[Path]:
    """Immediate child directories of each root that are git repositories."""
    seen: set[Path] = set()
    out: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        for child in sorted(root.iterdir()):
            if (child / ".git").exists() and child.resolve() not in seen:
                seen.add(child.resolve())
                out.append(child)
    return out
