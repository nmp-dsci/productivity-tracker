"""Read queries over the parquet rollups. Every function takes a DuckDB
connection with `daily`, `sessions` and `shiplog` views mounted (see `open_db`)
and returns plain JSON-able dicts.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

import duckdb

METRICS: list[tuple[str, str, str]] = [
    # key, label, note
    ("screen_hours", "Screen time", "display on, this Mac — as Screen Time counts it"),
    ("tok_out_per_hour", "Output tokens / hour", "output tokens ÷ screen time"),
    ("claude_sessions", "Sessions started", "interactive Claude Code, by first prompt"),
    ("automated_sessions", "Automated sessions", "subagents, eval loops, claude -p"),
    ("prompts", "Prompts sent", "human turns"),
    ("codex_sessions", "Codex sessions", "session files"),
    ("tokens_out", "Output tokens", "Claude Code + Codex"),
    ("tokens_in", "Input tokens", "uncached + cache write + cache read"),
    ("cache_read", "Cache reads", "≈ all of input on Claude Code"),
    ("cost_usd", "Agent $ (list price)", "derived from prices.yaml"),
    ("lavish", "Lavish pages", "review pages written"),
    ("commits", "Commits", "all repos, all branches"),
    ("prs", "PRs merged", "GitHub"),
    ("deploys", "Deploys", "App Runner + GitHub deployments"),
    ("projects", "Projects active", "repos with agent work or a commit"),
]

# Metrics that are a quotient of two others: summing daily ratios is wrong, so
# a window's value is sum(numerator) / sum(denominator).
RATIOS: dict[str, tuple[str, str]] = {"tok_out_per_hour": ("tokens_out", "screen_hours")}

_METRIC_SQL: dict[str, str] = {
    "screen_hours": "SELECT day, sum(seconds) / 3600 v FROM daily WHERE source='screen' AND kind='display_span' GROUP BY 1",
    # Interactive = at least one human prompt in history.jsonl. Automated =
    # subagents and the `claude -p` runs an eval loop fans out (no prompt).
    "claude_sessions": "SELECT day, count(*) v FROM sessions WHERE source='claude_code' AND prompts > 0 GROUP BY 1",
    "automated_sessions": "SELECT day, count(*) v FROM sessions WHERE source='claude_code' AND prompts = 0 GROUP BY 1",
    "codex_sessions": "SELECT day, count(*) v FROM sessions WHERE source='codex' GROUP BY 1",
    "prompts": "SELECT day, sum(n) v FROM daily WHERE source='claude_code' AND kind='prompt' GROUP BY 1",
    "tokens_out": "SELECT day, sum(tok_out) v FROM daily WHERE source IN ('claude_code','codex') GROUP BY 1",
    "tokens_in": "SELECT day, sum(tok_in + tok_cw + tok_cr) v FROM daily WHERE source IN ('claude_code','codex') GROUP BY 1",
    "cache_read": "SELECT day, sum(tok_cr) v FROM daily WHERE source IN ('claude_code','codex') GROUP BY 1",
    "cost_usd": "SELECT day, sum(cost_usd) v FROM daily WHERE source IN ('claude_code','codex') GROUP BY 1",
    "lavish": "SELECT day, sum(n) v FROM daily WHERE source='lavish' AND kind='page_created' GROUP BY 1",
    "commits": "SELECT day, sum(n) v FROM daily WHERE source='git_local' AND kind='commit' GROUP BY 1",
    "prs": "SELECT day, sum(n) v FROM daily WHERE source='github' AND kind='pr_merged' GROUP BY 1",
    # App Runner operations, GitHub deployment statuses, and successful CI
    # workflows whose name says deploy (the sibling repos deploy from Actions).
    "deploys": """SELECT day, count(*) v FROM shiplog WHERE (source='aws' AND kind='apprunner_deploy')
                  OR (source='github' AND kind='deployment_status' AND status='success')
                  OR (source='github' AND kind='workflow_run' AND status='success' AND lower(title) LIKE '%deploy%')
                  GROUP BY 1""",
    "projects": """SELECT day, count(DISTINCT project) v FROM daily
                   WHERE project IS NOT NULL AND ((source='git_local' AND kind='commit')
                   OR (source IN ('claude_code','codex') AND kind IN ('assistant_message','token_count'))) GROUP BY 1""",
}


def open_db(rollups_dir: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    for name in ("daily", "sessions", "shiplog"):
        p = (rollups_dir / f"{name}.parquet").as_posix()
        con.execute(f"CREATE OR REPLACE VIEW {name} AS SELECT * FROM read_parquet('{p}')")
    return con


def _rows(
    con: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None
) -> list[dict[str, Any]]:
    cur = con.execute(sql, params or [])
    cols = [d[0] for d in cur.description or []]
    return [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]


def _series(con: duckdb.DuckDBPyConnection, key: str, start: date, end: date) -> dict[str, float]:
    if key in RATIOS:
        num_key, den_key = RATIOS[key]
        num, den = _series(con, num_key, start, end), _series(con, den_key, start, end)
        return {d: num.get(d, 0.0) / v for d, v in den.items() if v > 0}
    sql = f"SELECT day, v FROM ({_METRIC_SQL[key]}) WHERE day BETWEEN ? AND ?"
    return {str(r["day"]): float(r["v"] or 0) for r in _rows(con, sql, [start, end])}


def _total(con: duckdb.DuckDBPyConnection, key: str, start: date, end: date) -> float:
    """A window's value: a sum, except for a ratio, which divides the summed
    numerator by the summed denominator."""
    if key in RATIOS:
        num_key, den_key = RATIOS[key]
        den = _total(con, den_key, start, end)
        return _total(con, num_key, start, end) / den if den > 0 else 0.0
    return sum(_series(con, key, start, end).values())


def _rolling(
    series: dict[str, float], end: date, n: int, size: int = 7
) -> list[tuple[date, date, float]]:
    """`n` buckets of `size` whole days each, the last ending on `end`.

    Calendar weeks leave a stub every Monday; anchoring on the last complete
    day instead means every bucket holds exactly `size` days, recomputed daily,
    so "this week vs last" compares like with like on any day of the week."""
    out: list[tuple[date, date, float]] = []
    for i in range(n - 1, -1, -1):
        stop = end - timedelta(days=size * i)
        start = stop - timedelta(days=size - 1)
        total = sum(series.get((start + timedelta(days=j)).isoformat(), 0.0) for j in range(size))
        out.append((start, stop, total))
    return out


def _blocks(
    con: duckdb.DuckDBPyConnection, key: str, end: date, n: int, size: int = 7
) -> list[tuple[date, date, float]]:
    """`_rolling` for one metric, dividing block sums for a ratio metric."""
    start = end - timedelta(days=n * size - 1)
    if key in RATIOS:
        num_key, den_key = RATIOS[key]
        num = _rolling(_series(con, num_key, start, end), end, n, size)
        den = _rolling(_series(con, den_key, start, end), end, n, size)
        return [
            (a, b, (nv / dv if dv > 0 else 0.0))
            for (a, b, nv), (_, _, dv) in zip(num, den, strict=True)
        ]
    return _rolling(_series(con, key, start, end), end, n, size)


def _growth(weeks: list[tuple[date, float]]) -> dict[str, float | None]:
    def pct(a: float, b: float) -> float | None:
        if b <= 0:
            return None if a <= 0 else float("inf")
        return round((a - b) / b * 100, 1)

    vals = [v for _, v in weeks]
    if len(vals) < 2:
        return {"wow": None, "w4": None}
    wow = pct(vals[-1], vals[-2])
    l4 = sum(vals[-4:])
    p4 = sum(vals[-8:-4]) if len(vals) >= 8 else 0
    w4 = pct(l4, p4) if len(vals) >= 5 else None
    return {"wow": None if wow == float("inf") else wow, "w4": None if w4 == float("inf") else w4}


def trends(con: duckdb.DuckDBPyConnection, grain: str, window: int, today: date) -> dict[str, Any]:
    """One row per metric. Periods still in progress (today, and the current
    week) are marked `done: false`: they are drawn differently and kept out of
    every comparison, so a half-finished week never reads as a collapse."""
    # Weeks are rolling 7-day blocks ending on the last complete day, so growth
    # always compares 7 whole days with the 7 whole days before them.
    last = today - timedelta(days=1)
    buckets = max(window if grain == "week" else 0, 9)
    start = min(today - timedelta(days=window - 1), last - timedelta(days=buckets * 7 - 1))
    rows = []
    for key, label, note in METRICS:
        series = _series(con, key, start, today)
        blocks = _blocks(con, key, last, buckets)
        full = [(a, v) for a, _, v in blocks]
        if grain == "day":
            days = [today - timedelta(days=i) for i in range(window - 1, -1, -1)]
            cells = [
                {"d": d.isoformat(), "v": series.get(d.isoformat(), 0.0), "done": d < today}
                for d in days
            ]
        else:
            cells = [
                {"d": a.isoformat(), "end": b.isoformat(), "v": v, "done": True}
                for a, b, v in blocks[-window:]
            ]
        done: list[float] = [float(c["v"]) for c in cells if c["done"]]  # type: ignore[arg-type]
        first = cells[0]["d"]
        window_start, window_end = date.fromisoformat(str(first)), last
        rows.append(
            {
                "key": key,
                "label": label,
                "note": note,
                # Totals and the ramp cover complete periods only; the cell for
                # the period in progress is still returned, flagged done=false.
                "total": _total(con, key, window_start, window_end),
                "all_time": _total(con, key, date(2000, 1, 1), last),
                "active": sum(1 for v in done if v),
                "periods": len(done),
                "spark": [v for _, v in full[-26:]],
                "growth": _growth(full),
                "cells": cells,
            }
        )
    return {
        "grain": grain,
        "window": window,
        "start": start.isoformat(),
        "end": today.isoformat(),
        # Last day that has actually finished — every bucket ends here or before.
        "complete_through": last.isoformat(),
        "rows": rows,
    }


def kpis(con: duckdb.DuckDBPyConnection, s: date, e: date) -> dict[str, float]:
    return {key: _total(con, key, s, e) for key, _, _ in METRICS}


def window_summary(con: duckdb.DuckDBPyConnection, start: date, end: date) -> dict[str, Any]:
    """KPIs for start..end against the same-length window before it, plus the
    per-project table, class split and ship log. Overview (calendar week) and
    Insights (rolling 7 days) are both this."""
    days = (end - start).days + 1
    p_end = start - timedelta(days=1)
    p_start = p_end - timedelta(days=days - 1)
    this, last = kpis(con, start, end), kpis(con, p_start, p_end)
    projects = _rows(
        con,
        """
        SELECT project,
               sum(CASE WHEN source IN ('claude_code','codex') THEN tok_out ELSE 0 END) AS tok_out,
               sum(CASE WHEN source IN ('claude_code','codex') THEN cost_usd ELSE 0 END) AS cost_usd,
               sum(CASE WHEN source='git_local' AND kind='commit' THEN n ELSE 0 END) AS commits,
               sum(CASE WHEN source='github' AND kind='pr_merged' THEN n ELSE 0 END) AS prs,
               sum(CASE WHEN source='lavish' AND kind='page_created' THEN n ELSE 0 END) AS pages,
               sum(CASE WHEN (source='aws' AND kind='apprunner_deploy') OR (source='github' AND kind='deployment_status') THEN n ELSE 0 END) AS deploys
        FROM daily WHERE day BETWEEN ? AND ? AND project IS NOT NULL
        GROUP BY 1 HAVING tok_out > 0 OR commits > 0 ORDER BY commits DESC, tok_out DESC LIMIT 40""",
        [start, end],
    )
    split = _rows(
        con,
        """
        SELECT cls, sum(tok_out) AS tok_out, sum(cost_usd) AS cost_usd FROM daily
        WHERE day BETWEEN ? AND ? AND source IN ('claude_code','codex') GROUP BY 1 ORDER BY 2 DESC""",
        [start, end],
    )
    ship = _rows(
        con,
        "SELECT ts, day, source, kind, project, title, status, url FROM shiplog WHERE day BETWEEN ? AND ? ORDER BY ts DESC LIMIT 40",
        [start, end],
    )
    metrics = []
    for key, label, note in METRICS:
        a, b = this[key], last[key]
        g = None if b <= 0 else round((a - b) / b * 100, 1)
        metrics.append(
            {"key": key, "label": label, "note": note, "value": a, "prior": b, "growth": g}
        )
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "prior_start": p_start.isoformat(),
        "prior_end": p_end.isoformat(),
        "kpis": this,
        "prior": last,
        "metrics": metrics,
        "projects": projects,
        "split": split,
        "shiplog": ship,
    }


def overview(con: duckdb.DuckDBPyConnection, week_start: date) -> dict[str, Any]:
    end = week_start + timedelta(days=6)
    out = window_summary(con, week_start, end)
    out["week_start"], out["week_end"] = week_start.isoformat(), end.isoformat()
    return out


def insights(con: duckdb.DuckDBPyConnection, today: date, narratives_dir: Path) -> dict[str, Any]:
    """Rolling 7 complete days vs the 7 before, plus the latest rolling narrative.

    The window ends yesterday: today is still in progress, and counting a part
    day against seven whole ones makes every metric look like it is falling."""
    end = today - timedelta(days=1)
    out = window_summary(con, end - timedelta(days=6), end)
    out["as_of"] = today.isoformat()
    # 26 rolling 7-day totals per metric, drawn behind each tile.
    for m in out["metrics"]:
        m["spark"] = [v for _, _, v in _blocks(con, m["key"], end, 26)]
    latest = sorted(narratives_dir.glob("rolling-*.md")) if narratives_dir.exists() else []
    out["narrative"] = latest[-1].read_text() if latest else None
    out["narrative_end"] = latest[-1].stem.removeprefix("rolling-") if latest else None
    return out


def agents(con: duckdb.DuckDBPyConnection, start: date, end: date) -> dict[str, Any]:
    by_day_model = _rows(
        con,
        """
        SELECT day, coalesce(model, 'unknown') AS model, sum(tok_out) AS tok_out, sum(tok_in) AS tok_in,
               sum(tok_cr) AS tok_cr, sum(tok_cw) AS tok_cw, sum(cost_usd) AS cost_usd, sum(n) AS msgs
        FROM daily WHERE day BETWEEN ? AND ? AND source IN ('claude_code','codex') AND kind IN ('assistant_message','token_count')
        GROUP BY 1, 2 ORDER BY 1, 2""",
        [start, end],
    )
    by_class = _rows(
        con,
        """
        SELECT cls, sum(tok_out) AS tok_out, sum(cost_usd) AS cost_usd, sum(n) AS msgs FROM daily
        WHERE day BETWEEN ? AND ? AND source IN ('claude_code','codex') AND kind IN ('assistant_message','token_count')
        GROUP BY 1 ORDER BY 2 DESC""",
        [start, end],
    )
    by_project = _rows(
        con,
        """
        SELECT project, cls, sum(tok_out) AS tok_out, sum(cost_usd) AS cost_usd FROM daily
        WHERE day BETWEEN ? AND ? AND source IN ('claude_code','codex') AND kind IN ('assistant_message','token_count') AND project IS NOT NULL
        GROUP BY 1, 2 ORDER BY 3 DESC""",
        [start, end],
    )
    tools = _rows(
        con,
        """
        SELECT t AS tool, count(*) AS sessions FROM (SELECT unnest(tools) AS t FROM sessions WHERE day BETWEEN ? AND ?)
        GROUP BY 1 ORDER BY 2 DESC LIMIT 20""",
        [start, end],
    )
    cache = _rows(
        con,
        """
        SELECT sum(tok_cr) AS cache_read, sum(tok_in) AS uncached, sum(tok_cw) AS cache_write FROM daily
        WHERE day BETWEEN ? AND ? AND source='claude_code'""",
        [start, end],
    )
    sessions = _rows(
        con,
        """
        SELECT session_id, source, project, branch, first_ts, last_ts, seconds, messages, prompts, tok_out, cost_usd, cls, models, subagent_msgs
        FROM sessions WHERE day BETWEEN ? AND ? AND messages > 0 ORDER BY first_ts DESC LIMIT 300""",
        [start, end],
    )
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "by_day_model": by_day_model,
        "by_class": by_class,
        "by_project": by_project,
        "tools": tools,
        "cache": cache[0] if cache else {},
        "sessions": sessions,
    }


def github(con: duckdb.DuckDBPyConnection, start: date, end: date) -> dict[str, Any]:
    commits = _rows(
        con,
        """
        SELECT day, project, sum(n) AS commits, sum(insertions) AS insertions, sum(deletions) AS deletions
        FROM daily WHERE day BETWEEN ? AND ? AND source='git_local' AND kind='commit' GROUP BY 1, 2 ORDER BY 1""",
        [start, end],
    )
    prs = _rows(
        con,
        """
        SELECT ts, day, project, branch, title, number, url, kind FROM shiplog
        WHERE day BETWEEN ? AND ? AND source='github' AND kind IN ('pr_merged','pr_opened') ORDER BY ts DESC LIMIT 200""",
        [start, end],
    )
    ci = _rows(
        con,
        """
        SELECT day, sum(CASE WHEN status='success' THEN 1 ELSE 0 END) AS passed,
               sum(CASE WHEN status='failure' THEN 1 ELSE 0 END) AS failed, count(*) AS runs
        FROM shiplog WHERE day BETWEEN ? AND ? AND source='github' AND kind='workflow_run' GROUP BY 1 ORDER BY 1""",
        [start, end],
    )
    branches = _rows(
        con,
        """
        SELECT project, branch, count(*) AS commits, min(day) AS first_day, max(day) AS last_day
        FROM daily WHERE day BETWEEN ? AND ? AND source='git_local' AND kind='commit' AND branch IS NOT NULL
        GROUP BY 1, 2 ORDER BY 5 DESC LIMIT 60""",
        [start, end],
    )
    gates = _rows(
        con,
        """
        SELECT day, status, count(*) AS n FROM shiplog WHERE day BETWEEN ? AND ? AND source='nomistakes' GROUP BY 1, 2 ORDER BY 1""",
        [start, end],
    )
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "commits": commits,
        "prs": prs,
        "ci": ci,
        "branches": branches,
        "gates": gates,
    }


def projects(con: duckdb.DuckDBPyConnection, start: date, end: date) -> list[dict[str, Any]]:
    return _rows(
        con,
        """
        SELECT project,
               sum(CASE WHEN source IN ('claude_code','codex') THEN tok_out ELSE 0 END) AS tok_out,
               sum(CASE WHEN source IN ('claude_code','codex') THEN cost_usd ELSE 0 END) AS agent_usd,
               sum(CASE WHEN source='aws' AND kind='daily_cost' THEN cost_usd ELSE 0 END) AS aws_usd,
               sum(CASE WHEN source='git_local' AND kind='commit' THEN n ELSE 0 END) AS commits,
               sum(CASE WHEN source='github' AND kind='pr_merged' THEN n ELSE 0 END) AS prs,
               sum(CASE WHEN source='lavish' AND kind='page_created' THEN n ELSE 0 END) AS pages,
               sum(CASE WHEN source='evals' THEN n ELSE 0 END) AS eval_runs,
               sum(CASE WHEN (source='aws' AND kind='apprunner_deploy') OR (source='github' AND kind='deployment_status') THEN n ELSE 0 END) AS deploys,
               max(CASE WHEN (source='aws' AND kind='apprunner_deploy') OR (source='github' AND kind='deployment_status') THEN day END) AS last_deploy,
               max(day) AS last_active
        FROM daily WHERE day BETWEEN ? AND ? AND project IS NOT NULL
        GROUP BY 1 ORDER BY tok_out DESC""",
        [start, end],
    )


def project_detail(
    con: duckdb.DuckDBPyConnection, name: str, start: date, end: date
) -> dict[str, Any]:
    daily = _rows(
        con,
        """
        SELECT day,
               sum(CASE WHEN source IN ('claude_code','codex') THEN tok_out ELSE 0 END) AS tok_out,
               sum(CASE WHEN source IN ('claude_code','codex') THEN cost_usd ELSE 0 END) AS cost_usd,
               sum(CASE WHEN source='git_local' AND kind='commit' THEN n ELSE 0 END) AS commits,
               sum(CASE WHEN source='lavish' THEN n ELSE 0 END) AS pages
        FROM daily WHERE project = ? AND day BETWEEN ? AND ? GROUP BY 1 ORDER BY 1""",
        [name, start, end],
    )
    split = _rows(
        con,
        "SELECT cls, sum(tok_out) AS tok_out FROM daily WHERE project = ? AND day BETWEEN ? AND ? AND source IN ('claude_code','codex') GROUP BY 1 ORDER BY 2 DESC",
        [name, start, end],
    )
    ship = _rows(
        con,
        "SELECT ts, kind, source, title, status, url, branch FROM shiplog WHERE project = ? AND day BETWEEN ? AND ? ORDER BY ts DESC LIMIT 50",
        [name, start, end],
    )
    return {"project": name, "daily": daily, "split": split, "shiplog": ship}


def shiplog(con: duckdb.DuckDBPyConnection, limit: int) -> list[dict[str, Any]]:
    return _rows(
        con,
        "SELECT ts, day, source, kind, project, repo, branch, title, status, url, number FROM shiplog ORDER BY ts DESC LIMIT ?",
        [limit],
    )
