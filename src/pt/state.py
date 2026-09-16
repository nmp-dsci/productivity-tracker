"""Collector state: byte offsets per file and last-seen markers, so every
collector is incremental and idempotent across runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class State:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._d: dict[str, Any] = {}
        if path.exists():
            try:
                self._d = json.loads(path.read_text())
            except json.JSONDecodeError:
                self._d = {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._d.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._d[key] = value

    def offsets(self, collector: str) -> dict[str, int]:
        return dict(self._d.setdefault("offsets", {}).setdefault(collector, {}))

    def set_offset(self, collector: str, file: str, offset: int) -> None:
        self._d.setdefault("offsets", {}).setdefault(collector, {})[file] = offset

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._d, indent=1, sort_keys=True))
        tmp.replace(self.path)
