"""Event schema v1 — the one row shape every source is normalised to.

Privacy invariant: no field may carry prompt or transcript text. Collectors
copy metadata (counts, tokens, paths, ids) and drop content at the source.
`tests/test_privacy.py` scans every fixture-derived event for long strings.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1

Source = Literal[
    "claude_code", "codex", "git_local", "github", "aws", "lavish", "evals", "nomistakes"
]
Class = Literal["building", "evals", "infra", "writing", "review", "unknown"]


class Tokens(BaseModel):
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    thinking: int = 0


class Event(BaseModel):
    event_id: str
    schema_version: int = Field(default=SCHEMA_VERSION, alias="schema")
    source: Source
    kind: str
    ts: datetime
    project: str | None = None
    repo: str | None = None
    branch: str | None = None
    session_id: str | None = None
    model: str | None = None
    tokens: Tokens | None = None
    cost_usd: float | None = None
    tools: list[str] = Field(default_factory=list)
    cls: Class = Field(default="unknown", alias="class")
    # Small, source-specific extras (counts, ids, statuses). Never text bodies.
    meta: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}

    def to_json(self) -> str:
        return self.model_dump_json(by_alias=True, exclude_none=True)


def event_id(source: str, *natural_key: object) -> str:
    """Deterministic id from the source and its natural key, so re-collecting
    the same file/commit/webhook never produces a second event."""
    h = hashlib.sha256()
    h.update(source.encode())
    for part in natural_key:
        h.update(b"\x1f")
        h.update(str(part).encode())
    return h.hexdigest()[:32]


def utc(ts: datetime | str | float | int) -> datetime:
    """Normalise anything the sources emit to an aware UTC datetime."""
    if isinstance(ts, datetime):
        return ts.astimezone(UTC) if ts.tzinfo else ts.replace(tzinfo=UTC)
    if isinstance(ts, int | float):
        # Claude Code history.jsonl uses epoch milliseconds.
        return datetime.fromtimestamp(ts / 1000 if ts > 1e11 else ts, tz=UTC)
    s = ts.replace("Z", "+00:00")
    return utc(datetime.fromisoformat(s))
