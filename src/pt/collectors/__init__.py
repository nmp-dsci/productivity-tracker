"""One module per source. Each exposes `collect(settings, state) -> Iterator[Event]`
and is pull-first, incremental and idempotent."""

from __future__ import annotations

from collections.abc import Callable, Iterator

from pt.config import Settings
from pt.schema import Event
from pt.state import State

Collector = Callable[[Settings, State], Iterator[Event]]


def registry() -> dict[str, Collector]:
    from pt.collectors import claude_code, codex, evals, git_local, lavish, nomistakes

    return {
        "claude_code": claude_code.collect,
        "codex": codex.collect,
        "git_local": git_local.collect,
        "lavish": lavish.collect,
        "evals": evals.collect,
        "nomistakes": nomistakes.collect,
    }
