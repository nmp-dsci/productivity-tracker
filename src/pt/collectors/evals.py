"""Eval runs: each repo keeps its own run format, so this is a tolerant
adapter over the shapes seen in the portfolio:

* `evals/runs/*.json`            — transcript-rag-agent (run_id, created_at, kind, metrics)
* `runs/<run>/run.json`          — DABStep-loop, tau2-loop (run_id, started_at, summary)
* `runs/<run>/*.json`            — ConvFinQA (config.json + results)

We keep the run id, kind, model, and up to eight numeric headline metrics.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pt.collectors._util import repos_under
from pt.config import Settings
from pt.schema import Event, Source, event_id, utc
from pt.state import State

SOURCE: Source = "evals"
_TS_KEYS = ("created_at", "started_at", "finished_at", "timestamp", "ts")
_METRIC_KEYS = ("metrics", "summary", "results", "scores")


def _numeric(d: Any, limit: int = 8) -> dict[str, float]:
    out: dict[str, float] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, bool):
                continue
            if isinstance(v, int | float):
                out[str(k)[:40]] = float(v)
            if len(out) >= limit:
                break
    return out


def run_event(path: Path, project: str) -> Event | None:
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    ts_raw = next((data[k] for k in _TS_KEYS if isinstance(data.get(k), str)), None)
    try:
        ts = utc(ts_raw) if ts_raw else datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    except ValueError:
        ts = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    metrics: dict[str, float] = {}
    for k in _METRIC_KEYS:
        metrics = _numeric(data.get(k))
        if metrics:
            break
    run_id = str(data.get("run_id") or path.parent.name if path.name == "run.json" else path.stem)
    return Event(
        event_id=event_id(SOURCE, str(path)),
        source=SOURCE,
        kind="run",
        ts=ts,
        project=project,
        model=data.get("model") if isinstance(data.get("model"), str) else None,
        cls="evals",
        meta={
            "run_id": run_id[:80],
            "run_kind": str(data.get("kind") or data.get("agent") or "")[:40],
            "n_tasks": data.get("n_tasks") if isinstance(data.get("n_tasks"), int) else None,
            "metrics": metrics,
            "file": path.name[:120],
        },
    )


def candidate_files(repo: Path) -> Iterator[Path]:
    yield from sorted((repo / "evals" / "runs").glob("*.json"))
    runs = repo / "runs"
    if runs.is_dir():
        for d in sorted(runs.iterdir()):
            if not d.is_dir():
                continue
            if (d / "run.json").exists():
                yield d / "run.json"
            else:
                yield from sorted(d.glob("*.json"))[:1]


def collect(settings: Settings, state: State) -> Iterator[Event]:
    seen: dict[str, float] = state.get("evals_seen", {})
    for repo in repos_under(settings.repo_roots):
        for path in candidate_files(repo):
            key = str(path)
            mtime = path.stat().st_mtime
            if seen.get(key) == mtime:
                continue
            ev = run_event(path, repo.name)
            if ev:
                yield ev
            seen[key] = mtime
    state.set("evals_seen", seen)
