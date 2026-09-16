from __future__ import annotations

from pt.collectors import registry
from pt.config import Settings
from pt.enrich import narrative, tagger
from pt.state import State
from pt.store.local import LocalStore
from pt.store.rollup import build


def _seed(settings: Settings, state: State) -> LocalStore:
    store = LocalStore(settings.events_dir)
    for c in registry().values():
        store.append(list(c(settings, state)))
    build(settings, settings.rollups_dir)
    return store


def test_parse_labels_is_tolerant() -> None:
    text = '```json\n{"id": "a", "class": "building", "confidence": 0.8},\n{"id": "b", "class": "nope"}\nnot json\n```'
    assert tagger.parse_labels(text) == {"a": ("building", 0.8)}


def test_tagger_writes_label_events_and_reruns_are_noops(settings: Settings, state: State) -> None:
    store = _seed(settings, state)
    calls: list[str] = []

    def fake(system: str, user: str, *, max_tokens: int) -> str:
        calls.append(user)
        # every candidate gets 'writing'
        ids = [line.split('"id": "')[1].split('"')[0] for line in user.splitlines()]
        return "\n".join(f'{{"id": "{i}", "class": "writing", "confidence": 0.7}}' for i in ids)

    msg = tagger.run(settings, complete=fake)
    labels = [e for e in store.read("claude_code") if e.kind == "label"]
    assert "tagged" in msg and labels, msg
    assert all("REDACTED" not in c for c in calls)  # metadata only reached the model
    assert {e.session_id for e in labels} == {"sess-3"} and labels[0].cls == "writing"
    assert tagger.run(settings, complete=fake) == "nothing to tag"
    build(settings, settings.rollups_dir)
    import duckdb

    con = duckdb.connect()
    row = con.execute(
        f"SELECT cls FROM '{settings.rollups_dir / 'sessions.parquet'}' WHERE session_id='sess-3'"
    ).fetchone()
    assert row and row[0] == "writing"  # label flowed into the rollup


def test_narrative_saves_markdown(settings: Settings, state: State) -> None:
    _seed(settings, state)
    seen: dict[str, str] = {}

    def fake(system: str, user: str, *, max_tokens: int) -> str:
        seen["user"] = user
        return "You shipped two commits and one review page.\n\nCommits rose.\n\nNothing odd."

    out = narrative.run(settings, week="2026-09-10", complete=fake)
    path = settings.data_dir / "narratives" / "2026-09-07.md"
    assert path.exists() and "review page" in path.read_text() and "wrote" in out
    assert '"commits": 2' in seen["user"]
