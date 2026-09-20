"""Codex CLI collector: `~/.codex/sessions/YYYY/MM/DD/*.jsonl`.

First line is `session_meta` (cwd, cli_version, model_provider); `event_msg`
lines with `payload.type == "token_count"` carry cumulative and last-turn
usage. Model name arrives on `turn_context` lines when present.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from pt.collectors._util import tail_jsonl
from pt.config import Settings
from pt.enrich.prices import cost_usd
from pt.schema import Event, Source, Tokens, event_id, utc
from pt.state import State

SOURCE: Source = "codex"


def session_events(
    lines: Iterator[dict[str, Any]], settings: Settings, file_key: str
) -> Iterator[Event]:
    session_id: str | None = None
    project: str | None = None
    model: str | None = None
    for line in lines:
        payload = line.get("payload") or {}
        ts = line.get("timestamp")
        kind = line.get("type")
        if kind == "session_meta":
            session_id = payload.get("id") or payload.get("session_id")
            project = settings.project_from_path(payload.get("cwd"))
            if ts and session_id:
                yield Event(
                    event_id=event_id(SOURCE, "session_start", session_id),
                    source=SOURCE,
                    kind="session_start",
                    ts=utc(ts),
                    project=project,
                    session_id=session_id,
                    meta={
                        "cli_version": payload.get("cli_version"),
                        "originator": payload.get("originator"),
                        "provider": payload.get("model_provider"),
                    },
                )
            continue
        if kind == "turn_context" and isinstance(payload.get("model"), str):
            model = payload["model"]
            continue
        if kind == "event_msg" and payload.get("type") == "token_count" and ts:
            info = payload.get("info") or {}
            last = info.get("last_token_usage") or {}
            if not last:
                continue
            tokens = Tokens(
                input=int(last.get("input_tokens") or 0)
                - int(last.get("cached_input_tokens") or 0),
                output=int(last.get("output_tokens") or 0),
                cache_read=int(last.get("cached_input_tokens") or 0),
                thinking=int(last.get("reasoning_output_tokens") or 0),
            )
            yield Event(
                event_id=event_id(SOURCE, "token_count", session_id or file_key, ts),
                source=SOURCE,
                kind="token_count",
                ts=utc(ts),
                project=project,
                session_id=session_id,
                model=model,
                tokens=tokens,
                cost_usd=cost_usd(model, tokens),
                cls="building",
            )


def collect(settings: Settings, state: State) -> Iterator[Event]:
    base = settings.codex_dir / "sessions"
    if not base.exists():
        return
    for path in sorted(base.glob("*/*/*/*.jsonl")):
        yield from session_events(tail_jsonl(path, state, SOURCE), settings, str(path))
