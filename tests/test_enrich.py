from __future__ import annotations

from pt.enrich.classify import classify, classify_command, classify_path
from pt.enrich.prices import cost_usd, price_for
from pt.schema import Tokens, event_id, utc


def test_prices_prefix_match_and_cache_multipliers() -> None:
    p = price_for("claude-haiku-4-5-20251001")
    assert p and p["input"] == 1.0 and p["cache_write"] == 1.25 and p["cache_read"] == 0.1
    assert price_for("claude-fable-5-1")["cache_read"] == 0.25  # type: ignore[index]
    assert price_for("gpt-5-codex") is None


def test_cost_arithmetic() -> None:
    t = Tokens(input=1_000_000, output=1_000_000, cache_read=1_000_000, cache_write=1_000_000)
    assert cost_usd("claude-opus-5", t) == 5 + 25 + 0.5 + 6.25
    assert cost_usd("unknown-model", t) is None


def test_classify_paths_and_commands() -> None:
    assert classify_path("src/pt/cli.py") == "building"
    assert classify_path("tests/test_cli.py") == "evals"
    assert classify_path("infra/terraform/demo/main.tf") == "infra"
    assert classify_path(".lavish/s00_plan.html") == "writing"
    assert classify_command("uv run pytest -q")[0] == "evals"
    assert classify_command("terraform apply")[0] == "infra"
    assert classify_command("git status")[0] == "review"
    cls, paths = classify_command("cat src/pt/cli.py | head")
    assert paths == ["src/pt/cli.py"]
    assert classify(["Read", "Grep"], []) == "review"
    assert classify(["Edit"], ["src/a.py", "tests/b.py", "src/c.py"]) == "building"


def test_event_id_and_utc() -> None:
    assert event_id("x", 1, "a") == event_id("x", 1, "a") != event_id("x", 1, "b")
    assert utc(1789000000000).isoformat() == "2026-09-10T00:26:40+00:00"
    assert utc("2026-09-10T12:00:00+10:00").isoformat() == "2026-09-10T02:00:00+00:00"
