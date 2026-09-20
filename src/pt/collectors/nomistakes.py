"""no-mistakes gate runs, from the daemon log.

`push received ref=refs/heads/<branch> ... gate=<repos>/<hash>.git` starts a
run; `pipeline completed|failed run_id=<ulid>` ends one. The gate hash maps
back to a portfolio repo through that repo's `no-mistakes` remote.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path

from pt.collectors._util import tail_lines
from pt.config import Settings, gate_projects
from pt.schema import Event, Source, event_id, utc
from pt.state import State

SOURCE: Source = "nomistakes"
_TIME = re.compile(r"^time=(\S+)")
_MSG = re.compile(r'msg="([^"]+)"')
_KV = re.compile(r'(\w+)=("[^"]*"|\S+)')


def gate_map(settings: Settings) -> dict[str, str]:
    """`<hash>.git` → project name, via each repo's no-mistakes remote."""
    return gate_projects(settings)


def parse_line(line: str, gates: dict[str, str]) -> Event | None:
    tm = _TIME.match(line)
    mm = _MSG.search(line)
    if not tm or not mm:
        return None
    ts, msg = tm.group(1), mm.group(1)
    kv = {k: v.strip('"') for k, v in _KV.findall(line)}
    if msg == "push received":
        gate = Path(kv.get("gate", "")).name
        branch = kv.get("ref", "").replace("refs/heads/", "")
        return Event(
            event_id=event_id(SOURCE, "gate_push", ts, gate, branch),
            source=SOURCE,
            kind="gate_push",
            ts=utc(ts),
            project=gates.get(gate),
            branch=branch,
            cls="infra",
            meta={"gate": gate, "new": kv.get("new", "")[:12]},
        )
    if msg in ("pipeline completed", "pipeline failed", "cancelled active run"):
        status = {"pipeline completed": "passed", "pipeline failed": "failed"}.get(msg, "cancelled")
        run_id = kv.get("run_id") or kv.get("run", "")
        return Event(
            event_id=event_id(SOURCE, "gate_run", ts, run_id, status),
            source=SOURCE,
            kind="gate_run",
            ts=utc(ts),
            cls="infra",
            meta={"run_id": run_id, "status": status},
        )
    return None


def collect(settings: Settings, state: State) -> Iterator[Event]:
    log = settings.nomistakes_dir / "logs" / "daemon.log"
    if not log.exists():
        return
    gates = gate_map(settings)
    for line in tail_lines(log, state, SOURCE):
        ev = parse_line(line, gates)
        if ev:
            yield ev
