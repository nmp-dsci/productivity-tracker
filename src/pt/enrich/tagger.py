"""Tier-2 classifier: label sessions tier 1 left `unknown`, from metadata only.

Two passes. Automated sessions (no human prompt) inside an eval-loop project
are `evals` by construction — no model call. Interactive unknowns go to Claude
in batches with project, branch, tools, paths, duration and size — never a
prompt. Results are written back as `label` events keyed by session id, so
`pt rollup` picks them up and a re-run is a no-op.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

import duckdb

from pt.config import Settings
from pt.enrich.llm import Completer, completer, strip_fences, tagger_model
from pt.schema import Class, Event, event_id
from pt.store.local import LocalStore
from pt.store.rollup import connect

CLASSES: tuple[Class, ...] = ("building", "evals", "infra", "writing", "review")
_LOOP_PROJECT = re.compile(r"(-loop|-bench|eval)", re.I)

SYSTEM = """You label coding-agent sessions by what the developer was doing.
Classes: building (writing product code), evals (tests, benchmarks, evaluation harnesses, scoring),
infra (deploy, terraform, docker, CI, cloud), writing (docs, plans, review pages, markdown), review (reading, exploring, git archaeology, no edits).
You only see metadata: project, branch, tools used, file paths touched, duration, message count.
Answer with one JSON object per line: {"id": "<session id>", "class": "<class>", "confidence": 0-1}. Nothing else."""


def candidates(con: duckdb.DuckDBPyConnection, limit: int) -> list[dict[str, Any]]:
    """Unknown sessions with their distinct paths, biggest first."""
    rows = con.execute(
        """
        WITH paths AS (
          SELECT session_id, list_distinct(flatten(list(json_extract_string(meta, '$.paths')::VARCHAR[]))) AS paths
          FROM events WHERE session_id IS NOT NULL AND kind = 'assistant_message' GROUP BY 1
        ), s AS (
          SELECT session_id, arg_max(project, ts) project, arg_max(branch, ts) branch,
                 min(ts) first_ts, max(ts) last_ts, count(*) messages,
                 sum(CASE WHEN kind='prompt' THEN 1 ELSE 0 END) prompts,
                 list_distinct(flatten(list(tools))) tools, sum(tok_out) tok_out
          FROM events WHERE source='claude_code' AND session_id IS NOT NULL GROUP BY 1
        ), labelled AS (SELECT DISTINCT session_id FROM events WHERE kind = 'label')
        SELECT s.*, coalesce(p.paths, []) AS paths
        FROM s LEFT JOIN paths p USING (session_id)
        WHERE s.session_id NOT IN (SELECT session_id FROM labelled)
          AND s.session_id NOT IN (
            SELECT session_id FROM events WHERE session_id IS NOT NULL AND cls <> 'unknown' GROUP BY 1)
          AND s.messages >= 3
        ORDER BY s.tok_out DESC LIMIT ?
        """,
        [limit],
    ).fetchall()
    cols = [
        "session_id",
        "project",
        "branch",
        "first_ts",
        "last_ts",
        "messages",
        "prompts",
        "tools",
        "tok_out",
        "paths",
    ]
    return [dict(zip(cols, r, strict=False)) for r in rows]


def label_event(session_id: str, cls: Class, confidence: float, how: str, ts: datetime) -> Event:
    return Event(
        event_id=event_id("claude_code", "label", session_id),
        source="claude_code",
        kind="label",
        ts=ts,
        session_id=session_id,
        cls=cls,
        meta={"confidence": round(confidence, 2), "how": how},
    )


def heuristic(c: dict[str, Any]) -> Class | None:
    if c["prompts"] == 0 and c["project"] and _LOOP_PROJECT.search(c["project"]):
        return "evals"
    return None


def _describe(c: dict[str, Any]) -> str:
    secs = int((c["last_ts"] - c["first_ts"]).total_seconds())
    paths = [p for p in (c["paths"] or []) if p][:15]
    return json.dumps(
        {
            "id": c["session_id"],
            "project": c["project"],
            "branch": c["branch"],
            "minutes": secs // 60,
            "messages": c["messages"],
            "prompts": c["prompts"],
            "tools": (c["tools"] or [])[:12],
            "paths": paths,
        }
    )


def parse_labels(text: str) -> dict[str, tuple[Class, float]]:
    out: dict[str, tuple[Class, float]] = {}
    for line in strip_fences(text).splitlines():
        line = line.strip().rstrip(",")
        if not line.startswith("{"):
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError:
            continue
        cls = d.get("class")
        if isinstance(d.get("id"), str) and cls in CLASSES:
            out[d["id"]] = (cls, float(d.get("confidence", 0.5)))
    return out


def run(
    settings: Settings, limit: int = 200, complete: Completer | None = None, batch: int = 25
) -> str:
    con = connect(settings)
    cands = candidates(con, limit)
    con.close()
    if not cands:
        return "nothing to tag"
    now = datetime.now(tz=UTC)
    store = LocalStore(settings.events_dir)
    todo: list[dict[str, Any]] = []
    heuristics: list[Event] = []
    for c in cands:
        h = heuristic(c)
        if h:
            heuristics.append(label_event(c["session_id"], h, 0.9, "heuristic", now))
        else:
            todo.append(c)
    # Persist the free labels before any network call so a failed model run
    # never loses them; model labels land per batch for the same reason.
    n = store.append(heuristics)
    if not todo:
        return f"tagged {n} sessions (heuristic only)"
    try:
        complete = complete or completer(tagger_model())
    except ImportError:
        return f"tagged {n} sessions (heuristic); model skipped — `uv sync --group enrich`"
    modelled = 0
    for i in range(0, len(todo), batch):
        chunk = todo[i : i + batch]
        try:
            text = complete(SYSTEM, "\n".join(_describe(c) for c in chunk), max_tokens=4000)
        except Exception as e:  # noqa: BLE001 — any provider error ends the run, keeping progress
            return f"tagged {n} sessions ({len(heuristics)} heuristic, {modelled} via model); model stopped: {type(e).__name__}"
        labels = [
            label_event(sid, cls, conf, "claude", now)
            for sid, (cls, conf) in parse_labels(text).items()
        ]
        modelled += store.append(labels)
        n += modelled
    return f"tagged {n} sessions ({len(heuristics)} heuristic, {modelled} via model)"
