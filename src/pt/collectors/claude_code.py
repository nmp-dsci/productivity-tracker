"""Claude Code collector.

Two files matter and they have different lifetimes:

* `~/.claude/history.jsonl` — one line per human prompt (`display`, `project`,
  `sessionId`, `timestamp` ms). Survives Claude Code's transcript cleanup, so
  it is the backfill source for sessions and prompts. We keep everything
  *except* `display` and `pastedContents` (prompt text).
* `~/.claude/projects/<slug>/**/*.jsonl` — full transcripts, purged after
  `cleanupPeriodDays` (default 30). Every assistant line carries `usage`,
  `model`, `cwd`, `gitBranch`, `version`; tool_use blocks carry the tool name
  and (for file tools) a `file_path`. Subagent transcripts live in a
  subdirectory named after the parent session.

One API response is written as *several* lines — one per content block
(thinking, text, each tool_use) — all sharing `message.id` and repeating the
same `usage`. Summing per line overcounts tokens 2-3×, so lines are folded
into one event per message id; the event id excludes the timestamp so a
message split across two collector runs still dedupes.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from pt.collectors._util import tail_jsonl
from pt.config import Settings
from pt.enrich.classify import classify, classify_command
from pt.enrich.prices import cost_usd
from pt.schema import Class, Event, Source, Tokens, event_id, utc
from pt.state import State

SOURCE: Source = "claude_code"
_MAX_PATHS = 20


def _usage_tokens(u: dict[str, Any]) -> Tokens:
    details = u.get("output_tokens_details") or {}
    return Tokens(
        input=int(u.get("input_tokens") or 0),
        output=int(u.get("output_tokens") or 0),
        cache_read=int(u.get("cache_read_input_tokens") or 0),
        cache_write=int(u.get("cache_creation_input_tokens") or 0),
        thinking=int(details.get("thinking_tokens") or 0),
    )


def _tool_blocks(message: dict[str, Any]) -> tuple[list[str], list[str], list[Class]]:
    """Tool names, file paths touched, and the class of any shell commands.
    Command text is classified here and dropped."""
    tools: list[str] = []
    paths: list[str] = []
    cmd_classes: list[Class] = []
    content = message.get("content")
    if not isinstance(content, list):
        return tools, paths, cmd_classes
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "tool_use":
            continue
        name = block.get("name")
        if isinstance(name, str):
            tools.append(name)
        inp = block.get("input") or {}
        fp = inp.get("file_path") or inp.get("notebook_path") or inp.get("path")
        if isinstance(fp, str) and len(paths) < _MAX_PATHS:
            paths.append(fp)
        cmd = inp.get("command")
        if name == "Bash" and isinstance(cmd, str):
            cls, cmd_paths = classify_command(cmd)
            cmd_classes.append(cls)
            paths.extend(cmd_paths[: max(0, _MAX_PATHS - len(paths))])
    return tools, paths, cmd_classes


def _relative_paths(paths: list[str], cwd: str | None) -> list[str]:
    if not cwd:
        return paths
    out = []
    for p in paths:
        out.append(p[len(cwd) + 1 :] if p.startswith(cwd + "/") else p)
    return out


def _message_event(
    lines: list[dict[str, Any]], settings: Settings, *, subagent: bool
) -> Event | None:
    """Fold the lines of one assistant message (same message.id) into one event."""
    first = lines[0]
    message = first.get("message") or {}
    usage = message.get("usage")
    ts = first.get("timestamp")
    if not usage or not ts:
        return None
    model = message.get("model")
    if model == "<synthetic>":
        return None
    tokens = _usage_tokens(usage)
    tools: list[str] = []
    paths: list[str] = []
    cmd_classes: list[Class] = []
    for ln in lines:
        t, p, c = _tool_blocks(ln.get("message") or {})
        tools += t
        paths += p
        cmd_classes += c
    cwd = first.get("cwd")
    rel_paths = _relative_paths(paths[:_MAX_PATHS], cwd)
    session_id = first.get("sessionId")
    msg_id = message.get("id") or first.get("uuid")
    return Event(
        event_id=event_id(SOURCE, "assistant_message", session_id, msg_id),
        source=SOURCE,
        kind="assistant_message",
        ts=utc(ts),
        project=settings.project_from_path(cwd),
        branch=first.get("gitBranch"),
        session_id=session_id,
        model=model,
        tokens=tokens,
        cost_usd=cost_usd(model, tokens),
        tools=tools,
        cls=classify(tools, rel_paths, cmd_classes),
        meta={
            "version": first.get("version"),
            "subagent": subagent,
            "paths": rel_paths,
            "cache_5m": (usage.get("cache_creation") or {}).get("ephemeral_5m_input_tokens", 0),
            "cache_1h": (usage.get("cache_creation") or {}).get("ephemeral_1h_input_tokens", 0),
        },
    )


def transcript_events(
    lines: Iterator[dict[str, Any]], settings: Settings, *, subagent: bool
) -> Iterator[Event]:
    """Group consecutive assistant lines by message id and emit one event each."""
    buf: list[dict[str, Any]] = []
    buf_id: str | None = None
    for line in lines:
        if line.get("type") != "assistant":
            continue
        msg = line.get("message") or {}
        if not msg.get("usage"):
            continue
        mid = msg.get("id") or line.get("uuid")
        if buf and mid != buf_id:
            ev = _message_event(buf, settings, subagent=subagent)
            if ev:
                yield ev
            buf = []
        buf.append(line)
        buf_id = mid
    if buf:
        ev = _message_event(buf, settings, subagent=subagent)
        if ev:
            yield ev


def history_event(line: dict[str, Any], settings: Settings) -> Event | None:
    ts = line.get("timestamp")
    session_id = line.get("sessionId")
    if not ts or not session_id:
        return None
    project_path = line.get("project")
    return Event(
        event_id=event_id(SOURCE, "prompt", session_id, ts),
        source=SOURCE,
        kind="prompt",
        ts=utc(ts),
        project=settings.project_from_path(project_path),
        session_id=session_id,
        meta={"chars": len(line.get("display") or ""), "pasted": bool(line.get("pastedContents"))},
    )


def collect(settings: Settings, state: State) -> Iterator[Event]:
    history = settings.claude_dir / "history.jsonl"
    if history.exists():
        for line in tail_jsonl(history, state, SOURCE):
            ev = history_event(line, settings)
            if ev:
                yield ev
    projects = settings.claude_dir / "projects"
    if not projects.exists():
        return
    for path in sorted(projects.glob("*/**/*.jsonl")):
        # projects/<slug>/<session>.jsonl is a top-level session;
        # projects/<slug>/<session>/<agent>.jsonl is a subagent transcript.
        subagent = len(path.relative_to(projects).parts) > 2
        yield from transcript_events(tail_jsonl(path, state, SOURCE), settings, subagent=subagent)
