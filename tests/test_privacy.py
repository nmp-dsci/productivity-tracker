"""The invariant every collector must hold: no prompt or transcript text.
Fixtures put the literal REDACTED wherever the real files carry text; if it
ever shows up in an event, a collector copied a content field."""

from __future__ import annotations

import json
from typing import Any

from pt.collectors import registry
from pt.config import Settings
from pt.state import State

MAX_STRING = 200


def _strings(obj: Any):  # type: ignore[no-untyped-def]
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def test_no_text_bodies_leak(settings: Settings, state: State) -> None:
    for name, collector in registry().items():
        for ev in collector(settings, state):
            payload = json.loads(ev.to_json())
            for s in _strings(payload):
                assert "REDACTED" not in s, f"{name}: copied text into {ev.kind}"
                assert len(s) <= MAX_STRING, f"{name}: string too long in {ev.kind}: {s[:60]}…"
