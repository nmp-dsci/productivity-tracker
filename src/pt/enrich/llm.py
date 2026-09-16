"""One place that talks to Claude, so the tagger and the narrative share the
client, the model choice and the no-key behaviour. Optional dependency:
`uv sync --group enrich`."""

from __future__ import annotations

import os
from typing import Any, Protocol


class Completer(Protocol):
    def __call__(self, system: str, user: str, *, max_tokens: int) -> str: ...


def completer(model: str) -> Completer:
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


__all__: list[str] = [
    "Completer",
    "completer",
    "tagger_model",
    "narrative_model",
    "strip_fences",
    "Any",
]
