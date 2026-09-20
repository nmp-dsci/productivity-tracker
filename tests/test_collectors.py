from __future__ import annotations

from pt.collectors import registry
from pt.collectors.claude_code import collect as collect_claude
from pt.collectors.codex import collect as collect_codex
from pt.collectors.evals import collect as collect_evals
from pt.collectors.git_local import collect as collect_git
from pt.collectors.lavish import collect as collect_lavish
from pt.collectors.nomistakes import collect as collect_nm
from pt.config import Settings
from pt.state import State
from pt.store.local import LocalStore


def test_claude_folds_multiline_messages_and_skips_synthetic(
    settings: Settings, state: State
) -> None:
    events = list(collect_claude(settings, state))
    msgs = [e for e in events if e.kind == "assistant_message"]
    prompts = [e for e in events if e.kind == "prompt"]
    assert len(prompts) == 3
    # msg_1 spans three lines with identical usage → one event, tokens counted once
    m1 = next(e for e in msgs if e.meta.get("version") == "2.1.259" and e.model == "claude-opus-5")
    assert m1.tokens and m1.tokens.output == 500 and m1.tokens.thinking == 200
    assert sorted(m1.tools) == ["Bash", "Edit"]
    assert m1.meta["paths"] == ["src/alpha/core.py", "tests/test_core.py"]
    assert m1.project == "alpha" and m1.branch == "main"
    assert m1.cost_usd and m1.cost_usd > 0
    assert all(e.model != "<synthetic>" for e in msgs)
    assert (
        len([m for m in msgs if m.session_id == "sess-1"]) == 3
    )  # msg_1, msg_2, subagent msg_sub_1
    sub = next(e for e in msgs if e.meta.get("subagent"))
    assert sub.project == "alpha"  # scratchpad slug resolved


def test_claude_prompt_events_carry_no_text(settings: Settings, state: State) -> None:
    for e in collect_claude(settings, state):
        assert "display" not in e.meta and "REDACTED" not in e.to_json()


def test_codex(settings: Settings, state: State) -> None:
    events = list(collect_codex(settings, state))
    kinds = [e.kind for e in events]
    assert kinds == ["session_start", "token_count", "token_count"]
    tc = events[1]
    assert tc.tokens and tc.tokens.cache_read == 6016 and tc.tokens.input == 26353 - 6016
    assert tc.model == "gpt-5-codex" and tc.project == "beta"


def test_git_local(settings: Settings, state: State) -> None:
    events = list(collect_git(settings, state))
    commits = [e for e in events if e.kind == "commit"]
    assert len(commits) == 2
    assert {c.branch for c in commits} >= {"feature/x"}
    bump = next(c for c in commits if c.meta["subject"] == "fix: bump")
    assert bump.meta["insertions"] == 2 and bump.meta["deletions"] == 1
    assert any(e.kind == "branch_switch" and e.branch == "feature/x" for e in events)
    # second run is incremental and yields the same ids
    ids = {e.event_id for e in events}
    again = {e.event_id for e in collect_git(settings, state)}
    assert again <= ids


def test_lavish_and_evals(settings: Settings, state: State) -> None:
    pages = list(collect_lavish(settings, state))
    assert len(pages) == 1 and pages[0].meta["title"] == "Alpha plan" and pages[0].meta["seq"] == 0
    assert list(collect_lavish(settings, state)) == []  # unchanged → nothing new
    runs = list(collect_evals(settings, state))
    assert len(runs) == 1 and runs[0].meta["metrics"] == {"accuracy": 0.8, "n": 10.0}
    assert runs[0].model == "claude-haiku-4-5" and runs[0].cls == "evals"


def test_nomistakes(settings: Settings, state: State) -> None:
    events = list(collect_nm(settings, state))
    assert [e.kind for e in events] == ["gate_push", "gate_run", "gate_run"]
    assert events[0].project == "alpha" and events[0].branch == "fix-drift"
    assert [e.meta["status"] for e in events[1:]] == ["passed", "failed"]


def test_end_to_end_is_idempotent(settings: Settings, state: State) -> None:
    store = LocalStore(settings.events_dir)
    first = sum(store.append(list(c(settings, state))) for c in registry().values())
    state.save()
    state2 = State(settings.state_dir / "state.json")
    second = sum(store.append(list(c(settings, state2))) for c in registry().values())
    assert first > 0 and second == 0
    assert store.count() == first
