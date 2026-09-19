"""FastAPI app: `/api/*` reads over the parquet rollups, `/ingest/*` accepts
GitHub and EventBridge webhooks, and the built frontend is served from `/`.

Demo mode (`PT_DEMO_MODE=1`) is read-only and aggregates-only: ingest routes
disappear, and responses are stripped of session ids, branch names, URLs
and file paths before they leave the process.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from pt import __version__
from pt.api import queries as q
from pt.config import Settings, settings
from pt.schema import Event
from pt.store.local import LocalStore

# `project` is intentionally NOT redacted: all repos are public under the
# nmp-dsci account and the per-project breakdown is the point of the demo.
REDACT_KEYS = {"session_id", "branch", "url", "repo", "paths", "models", "number"}


def _redact(obj: Any) -> Any:
    """Aggregates only: drop identifying keys recursively (demo mode)."""
    if isinstance(obj, dict):
        return {k: _redact(v) for k, v in obj.items() if k not in REDACT_KEYS}
    if isinstance(obj, list):
        return [_redact(v) for v in obj]
    return obj


def _json_default(o: Any) -> Any:
    if isinstance(o, datetime | date):
        return o.isoformat()
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return str(o)


class _Response(JSONResponse):
    def render(self, content: Any) -> bytes:
        return json.dumps(content, default=_json_default, separators=(",", ":")).encode()


def create_app(cfg: Settings | None = None) -> FastAPI:
    cfg = cfg or settings()
    app = FastAPI(
        title="productivity-tracker", version=__version__, default_response_class=_Response
    )
    app.state.settings = cfg

    def today() -> date:
        return datetime.now(UTC).astimezone().date()

    def db() -> duckdb.DuckDBPyConnection:
        if not (cfg.rollups_dir / "daily.parquet").exists():
            raise HTTPException(503, "no rollups yet — run `pt collect && pt rollup`")
        return q.open_db(cfg.rollups_dir)

    def out(payload: Any) -> Any:
        return _redact(payload) if cfg.demo_mode else payload

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        daily = cfg.rollups_dir / "daily.parquet"
        return {
            "ok": True,
            "version": __version__,
            "demo": cfg.demo_mode,
            "rollups_at": datetime.fromtimestamp(daily.stat().st_mtime, tz=UTC).isoformat()
            if daily.exists()
            else None,
        }

    @app.get("/api/trends")
    def trends(
        grain: str = Query("day", pattern="^(day|week)$"), window: int = Query(90, ge=7, le=730)
    ) -> Any:
        with db() as con:
            return out(q.trends(con, grain, window, today()))

    @app.get("/api/insights")
    def insights() -> Any:
        with db() as con:
            return out(q.insights(con, today(), cfg.data_dir / "narratives"))

    @app.get("/api/overview")
    def overview(week: str | None = None) -> Any:
        d = date.fromisoformat(week) if week else today()
        start = d - timedelta(days=d.weekday())
        with db() as con:
            return out(q.overview(con, start))

    @app.get("/api/agents")
    def agents(days: int = Query(30, ge=1, le=365)) -> Any:
        end = today()
        with db() as con:
            return out(q.agents(con, end - timedelta(days=days - 1), end))

    @app.get("/api/github")
    def github(days: int = Query(90, ge=1, le=365)) -> Any:
        end = today()
        with db() as con:
            return out(q.github(con, end - timedelta(days=days - 1), end))

    @app.get("/api/projects")
    def projects(days: int = Query(90, ge=1, le=730)) -> Any:
        end = today()
        with db() as con:
            return out(q.projects(con, end - timedelta(days=days - 1), end))

    @app.get("/api/projects/{name}")
    def project(name: str, days: int = Query(90, ge=1, le=730)) -> Any:
        end = today()
        with db() as con:
            return out(q.project_detail(con, name, end - timedelta(days=days - 1), end))

    @app.get("/api/shiplog")
    def shiplog(limit: int = Query(100, ge=1, le=1000)) -> Any:
        with db() as con:
            return out(q.shiplog(con, limit))

    @app.get("/api/weekly")
    def weekly(week: str | None = None) -> Any:
        d = date.fromisoformat(week) if week else today() - timedelta(days=7)
        start = d - timedelta(days=d.weekday())
        path = cfg.data_dir / "narratives" / f"{start.isoformat()}.md"
        return {
            "week_start": start.isoformat(),
            "narrative": path.read_text() if path.exists() else None,
        }

    if not cfg.demo_mode:
        _mount_ingest(app, cfg)

    dist = Path("frontend/dist")
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str) -> FileResponse:
            candidate = dist / path
            if path and candidate.is_file():
                return FileResponse(candidate)
            return FileResponse(dist / "index.html")

    return app


def _mount_ingest(app: FastAPI, cfg: Settings) -> None:
    from pt.collectors.aws import parse_eventbridge
    from pt.collectors.github import parse_webhook, verify_signature

    store = LocalStore(cfg.events_dir)

    def persist(events: list[Event]) -> int:
        if not events:
            return 0
        n = store.append(events)
        if cfg.s3_bucket:
            from pt.store.s3 import put_events

            by_day: dict[tuple[str, str], list[str]] = {}
            for ev in events:
                by_day.setdefault((ev.source, ev.ts.date().isoformat()), []).append(ev.to_json())
            for (source, day), lines in by_day.items():
                put_events(cfg, source, day, lines)
        return n

    @app.post("/ingest/github")
    async def ingest_github(request: Request) -> dict[str, Any]:
        body = await request.body()
        if not cfg.ingest_secret or not verify_signature(
            cfg.ingest_secret, body, request.headers.get("X-Hub-Signature-256")
        ):
            raise HTTPException(401, "bad signature")
        event_name = request.headers.get("X-GitHub-Event", "")
        if event_name == "ping":
            return {"ok": True, "pong": True}
        events = list(parse_webhook(event_name, json.loads(body)))
        return {"ok": True, "event": event_name, "written": persist(events)}

    @app.post("/ingest/aws")
    async def ingest_aws(request: Request) -> dict[str, Any]:
        # EventBridge API destinations send a static bearer header we configure.
        auth = request.headers.get("Authorization", "")
        if not cfg.ingest_secret or auth != f"Bearer {cfg.ingest_secret}":
            raise HTTPException(401, "bad token")
        events = list(parse_eventbridge(await request.json()))
        return {"ok": True, "written": persist(events)}
