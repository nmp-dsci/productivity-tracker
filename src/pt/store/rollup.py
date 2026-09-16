"""DuckDB rollups: events JSONL → parquet tables the API reads.

Runs on the laptop (`pt rollup`), in CI (hourly, over the S3 mirror), and at
image build time for the demo snapshot. Pure function of the event store.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import duckdb

from pt.config import Settings

TABLES = ("daily", "sessions", "shiplog")


def _lit(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _sql(name: str, **params: str) -> str:
    """Load a query and splice in config literals. CREATE VIEW cannot take
    prepared parameters, and every value here is our own config, not input."""
    text = resources.files("pt.store").joinpath("queries", f"{name}.sql").read_text()
    for key, value in params.items():
        text = text.replace(f"${key}", _lit(value))
    return text


def connect(settings: Settings, events_dir: Path | None = None) -> duckdb.DuckDBPyConnection:
    """In-memory DuckDB with the `events` view mounted over the JSONL store."""
    con = duckdb.connect()
    con.execute("SET TimeZone = 'UTC'")
    glob = str((events_dir or settings.events_dir) / "*" / "*.jsonl")
    con.execute(_sql("events", tz=settings.timezone, glob=glob))
    return con


def build(settings: Settings, out_dir: Path) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    con = connect(settings)
    rows: dict[str, int] = {}
    for name in TABLES:
        target = (out_dir / f"{name}.parquet").as_posix()
        sql = _sql(name, tz=settings.timezone).strip().rstrip(";")
        con.execute(f"COPY ({sql}) TO '{target}' (FORMAT PARQUET)")
        rows[name] = int(con.execute(f"SELECT count(*) FROM '{target}'").fetchone()[0])  # type: ignore[index]
    con.close()
    return rows
