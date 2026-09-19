"""Token → USD. Model ids are matched by prefix so dated snapshots
(`claude-haiku-4-5-20251001`) price like their alias."""

from __future__ import annotations

from functools import lru_cache
from importlib import resources
from typing import Any

import yaml

from pt.schema import Tokens


@lru_cache(maxsize=1)
def table() -> dict[str, Any]:
    with resources.files("pt.enrich").joinpath("prices.yaml").open() as fh:
        data: dict[str, Any] = yaml.safe_load(fh)
    return data


def price_for(model: str | None) -> dict[str, float] | None:
    if not model:
        return None
    t = table()
    models: dict[str, dict[str, float]] = t["models"]
    # Longest matching prefix wins (claude-opus-4-8 before claude-opus-4).
    best = max((k for k in models if model.startswith(k)), key=len, default=None)
    if best is None:
        return None
    p = dict(models[best])
    p.setdefault("cache_write", p["input"] * t["default_cache_write_multiplier"])
    p.setdefault("cache_read", p["input"] * t["default_cache_read_multiplier"])
    return p


def cost_usd(model: str | None, tokens: Tokens | None) -> float | None:
    p = price_for(model)
    if p is None or tokens is None:
        return None
    usd = (
        tokens.input * p["input"]
        + tokens.output * p["output"]
        + tokens.cache_read * p["cache_read"]
        + tokens.cache_write * p["cache_write"]
    ) / 1_000_000
    return round(usd, 6)
