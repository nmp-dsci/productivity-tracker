"""`pt` — collect, roll up, serve.

pt collect [--source X] [--dry-run]     pull local sources into data/events/
pt rollup                                DuckDB → data/rollups/*.parquet
pt serve [--port 8080]                   FastAPI + built frontend
pt sync push|pull                        mirror data/ to/from S3 (PT_S3_BUCKET)
pt github install-hooks|backfill         GitHub webhooks and history
pt aws collect                           Cost Explorer + App Runner
pt tag                                   tier-2 classifier over unknown sessions
pt screen-backfill                       screen time history from knowledgeC.db
pt refresh                               full re-read + rebuild, once per UTC day
pt status                                how current the data behind the app is
pt weekly                                draft the weekly narrative
"""

from __future__ import annotations

import time
from pathlib import Path

import typer

from pt.config import settings

app = typer.Typer(no_args_is_help=True, add_completion=False, help=__doc__)
github_app = typer.Typer(no_args_is_help=True, help="GitHub webhooks and backfill.")
aws_app = typer.Typer(no_args_is_help=True, help="AWS collectors.")
sync_app = typer.Typer(no_args_is_help=True, help="S3 mirror of data/.")
app.add_typer(github_app, name="github")
app.add_typer(aws_app, name="aws")
app.add_typer(sync_app, name="sync")


@app.command()
def collect(
    source: list[str] = typer.Option([], "--source", "-s", help="Only these sources."),
    dry_run: bool = typer.Option(False, help="Parse but write nothing (state untouched)."),
) -> None:
    """Run the local collectors and append new events to the store."""
    from pt.collectors import registry
    from pt.state import State
    from pt.store.local import LocalStore

    cfg = settings()
    reg = registry()
    names = source or list(reg)
    unknown = [n for n in names if n not in reg]
    if unknown:
        raise typer.BadParameter(f"unknown source(s): {', '.join(unknown)}")
    state = State(cfg.state_dir / "state.json")
    store = LocalStore(cfg.events_dir)
    total = 0
    for name in names:
        t0 = time.time()
        events = list(reg[name](cfg, state))
        written = 0 if dry_run else store.append(events)
        total += written
        typer.echo(
            f"{name:12s} parsed {len(events):7d}  new {written:7d}  {time.time() - t0:5.1f}s"
        )
    if not dry_run:
        state.save()
    typer.echo(f"total new events: {total}")


@app.command()
def rollup(out: Path | None = typer.Option(None, help="Override rollups dir.")) -> None:
    """Build parquet rollups from the event store with DuckDB."""
    from pt.store.rollup import build

    cfg = settings()
    result = build(cfg, out or cfg.rollups_dir)
    for name, rows in result.items():
        typer.echo(f"{name:14s} {rows:8d} rows")


@app.command()
def serve(host: str = "127.0.0.1", port: int = 8080, reload: bool = False) -> None:
    """Serve the API and the built frontend."""
    import uvicorn

    uvicorn.run("pt.api.app:create_app", host=host, port=port, reload=reload, factory=True)


@sync_app.command("push")
def sync_push() -> None:
    """Upload data/events and data/rollups to S3."""
    from pt.store.s3 import push

    typer.echo(f"uploaded {push(settings())} objects")


@sync_app.command("pull")
def sync_pull() -> None:
    """Download data/events and data/rollups from S3."""
    from pt.store.s3 import pull

    typer.echo(f"downloaded {pull(settings())} objects")


@github_app.command("install-hooks")
def github_install_hooks(
    url: str = typer.Argument(..., help="Public ingest URL, e.g. https://…/ingest/github"),
    dry_run: bool = False,
) -> None:
    """Create or update a webhook on every repo owned by PT_GITHUB_OWNER."""
    from pt.collectors.github import install_hooks

    for line in install_hooks(settings(), url, dry_run=dry_run):
        typer.echo(line)


@github_app.command("backfill")
def github_backfill(days: int = typer.Option(365, help="How far back to walk.")) -> None:
    """Walk PRs, workflow runs and deployments via the REST API into the store."""
    from pt.collectors.github import backfill
    from pt.state import State
    from pt.store.local import LocalStore

    cfg = settings()
    state = State(cfg.state_dir / "state.json")
    n = LocalStore(cfg.events_dir).append(backfill(cfg, state, days=days))
    state.save()
    typer.echo(f"github backfill: {n} new events")


@aws_app.command("collect")
def aws_collect(days: int = typer.Option(30, help="Cost Explorer window.")) -> None:
    """Pull daily cost by project tag and App Runner service state."""
    from pt.collectors.aws import collect as aws_collect_
    from pt.state import State
    from pt.store.local import LocalStore

    cfg = settings()
    state = State(cfg.state_dir / "state.json")
    n = LocalStore(cfg.events_dir).append(aws_collect_(cfg, state, days=days))
    state.save()
    typer.echo(f"aws: {n} new events")


@app.command("screen-backfill")
def screen_backfill(
    days: int = typer.Option(45, help="How far back to read (Apple keeps ~30 days)."),
) -> None:
    """One-off: display spans from knowledgeC.db (needs Full Disk Access)."""
    from pt.collectors.screen import backfill
    from pt.state import State
    from pt.store.local import LocalStore

    cfg = settings()
    state = State(cfg.state_dir / "state.json")
    try:
        n = LocalStore(cfg.events_dir).append(backfill(cfg, state, days=days))
    except PermissionError as exc:
        typer.secho(str(exc), fg="red")
        raise typer.Exit(1) from exc
    typer.echo(f"screen backfill: {n} new events")


@app.command()
def refresh(
    force: bool = typer.Option(False, help="Refresh even if today's UTC day is already done."),
    deep: bool = typer.Option(
        True, help="Clear tail offsets so every source file is re-read from the top."
    ),
    remote: bool = typer.Option(True, help="Also re-walk GitHub and AWS."),
    github_days: int = typer.Option(30, help="GitHub backfill window."),
) -> None:
    """Full rebuild, once per UTC day.

    The 5-minute tick is incremental and forward-only; this re-reads every
    source from the top, re-walks the remote APIs and rebuilds the rollups, so
    edited files, late webhooks and Apple's shifting Screen Time window all
    settle. Re-collecting is safe: event ids are deterministic, so everything
    already stored dedupes away. It no-ops when the current UTC day has
    already been refreshed, which makes it safe to call from a timer that
    fires far more often than daily."""
    from collections.abc import Callable, Iterator
    from datetime import UTC, datetime

    from pt.collectors import registry
    from pt.schema import Event
    from pt.state import State
    from pt.store.local import LocalStore
    from pt.store.rollup import build

    cfg = settings()
    today = datetime.now(UTC).date().isoformat()
    state = State(cfg.state_dir / "state.json")
    if not force and state.get("last_full_refresh") == today:
        typer.echo(f"refresh: already done for {today} (UTC) — nothing to do")
        return

    t0 = time.time()
    if deep:
        state.clear_cursors()
    store = LocalStore(cfg.events_dir)
    total = 0
    for name, collect_ in registry().items():
        n = store.append(collect_(cfg, state))
        total += n
        typer.echo(f"{name:12s} new {n:7d}")
    from pt.collectors.screen import backfill as screen_backfill

    try:
        total += store.append(screen_backfill(cfg, state))
    except PermissionError as exc:
        typer.secho(f"screen backfill skipped: {exc}", fg="yellow")
    if remote:
        from pt.collectors.aws import collect as aws_collect_
        from pt.collectors.github import backfill as github_backfill

        remotes: list[tuple[str, Callable[[], Iterator[Event]]]] = [
            ("github", lambda: github_backfill(cfg, state, days=github_days)),
            ("aws", lambda: aws_collect_(cfg, state, days=github_days)),
        ]
        for label, events in remotes:
            try:
                n = store.append(events())
                total += n
                typer.echo(f"{label:12s} new {n:7d}")
            except Exception as exc:  # noqa: BLE001 — a missing token must not fail the day
                typer.secho(f"{label} skipped: {exc}", fg="yellow")
    build(cfg, cfg.rollups_dir)
    state.set("last_full_refresh", today)
    state.save()
    typer.echo(f"refresh {today} (UTC): {total} new events in {time.time() - t0:.0f}s")


@app.command()
def status() -> None:
    """How current is the data? Exits 1 when something needs a human.

    Prints the last day carrying an event for every source and kind, when the
    daily full refresh last ran, and whether Apple's Screen Time store is
    actually readable from this process — the one input that fails silently,
    because losing Full Disk Access makes the screen-time metric go quiet
    while every scheduled job still exits 0."""
    from pt.freshness import check
    from pt.state import State

    cfg = settings()
    lines, problems = check(cfg, State(cfg.state_dir / "state.json"))
    for line in lines:
        typer.echo(line)
    for problem in problems:
        typer.secho(f"\nPROBLEM  {problem}", fg="red")
    if problems:
        raise typer.Exit(1)


@app.command()
def tag(limit: int = typer.Option(200, help="Max sessions to tag this run.")) -> None:
    """Tier-2 classifier: label `unknown` sessions from metadata with Claude."""
    from pt.enrich.tagger import run

    typer.echo(run(settings(), limit=limit))


@app.command()
def weekly(
    week: str | None = typer.Option(
        None, help="ISO date inside a calendar week; default: rolling last 7 days."
    ),
    max_age_hours: float | None = typer.Option(
        None, help="Skip when the narrative is newer than this (the launchd job passes 24)."
    ),
) -> None:
    """Draft the narrative (rolling 7 days, or a calendar week) from the rollups."""
    from pt.enrich.narrative import run

    typer.echo(run(settings(), week=week, max_age_hours=max_age_hours))


if __name__ == "__main__":
    app()
