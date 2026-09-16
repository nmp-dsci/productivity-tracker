"""One place that talks to Claude, so the tagger and the narrative share the
backend choice and the no-key behaviour.

Two backends:

* ``subscription`` (default when ``CLAUDE_CODE_OAUTH_TOKEN`` is set) — the
  Claude Agent SDK drives the ``claude`` CLI, billed to the Claude
  subscription. ``ANTHROPIC_API_KEY`` is blanked for that subprocess so the
  CLI never silently falls back to pay-as-you-go.
* ``api`` — the Anthropic SDK against ``ANTHROPIC_API_KEY``.

Pick explicitly with ``PT_LLM_BACKEND=subscription|api``. Optional deps:
``uv sync --group enrich``.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Protocol

log = logging.getLogger(__name__)


class Completer(Protocol):
    def __call__(self, system: str, user: str, *, max_tokens: int) -> str: ...


def backend() -> str:
    explicit = os.environ.get("PT_LLM_BACKEND")
    if explicit in ("subscription", "api"):
        return explicit
    return "subscription" if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") else "api"


def _sdk_env() -> dict[str, str]:
    env: dict[str, str] = {}
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") and os.environ.get("ANTHROPIC_API_KEY"):
        env["ANTHROPIC_API_KEY"] = ""  # subscription, never the key
    elif not os.environ.get("CLAUDE_CODE_OAUTH_TOKEN"):
        log.warning(
            "CLAUDE_CODE_OAUTH_TOKEN not set; the claude CLI will use whatever login it has"
        )
    return env


def subscription_completer(model: str) -> Completer:
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

    async def _run(system: str, user: str, max_tokens: int) -> str:
        options = ClaudeAgentOptions(
            model=model,
            system_prompt=system,
            allowed_tools=[],
            disallowed_tools=["Bash", "Read", "Write", "Edit", "WebFetch", "WebSearch", "Task"],
            max_turns=1,
            setting_sources=[],
            continue_conversation=False,
            env=_sdk_env(),
            max_buffer_size=max(max_tokens * 8, 1_000_000),
        )
        chunks: list[str] = []
        async for message in query(prompt=user, options=options):
            if isinstance(message, AssistantMessage):
                chunks.extend(b.text for b in message.content if isinstance(b, TextBlock))
        return "".join(chunks)

    def run(system: str, user: str, *, max_tokens: int) -> str:
        return asyncio.run(_run(system, user, max_tokens))

    return run


def api_completer(model: str) -> Completer:
    import anthropic

    client = anthropic.Anthropic()

    def run(system: str, user: str, *, max_tokens: int) -> str:
        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        ) as stream:
            msg = stream.get_final_message()
        return "".join(b.text for b in msg.content if b.type == "text")

    return run


def completer(model: str) -> Completer:
    return subscription_completer(model) if backend() == "subscription" else api_completer(model)


def tagger_model() -> str:
    return os.environ.get("PT_TAGGER_MODEL", "claude-haiku-4-5")


def narrative_model() -> str:
    return os.environ.get("PT_NARRATIVE_MODEL", "claude-opus-5")


def strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[1] if "\n" in t else ""
        t = t.rsplit("```", 1)[0]
    return t.strip()
