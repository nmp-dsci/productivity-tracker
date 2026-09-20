"""Tier-1 classifier: deterministic, path- and tool-based, runs in the collector.

Tier 2 (`tagger.py`) only sees sessions tier 1 leaves as `unknown`, and only
their metadata — never prompt text.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from pt.schema import Class

_RULES: list[tuple[Class, re.Pattern[str]]] = [
    ("evals", re.compile(r"(^|/)(evals?|tests?|benchmarks?|runs|golden)(/|$)|_eval|test_|_test\.")),
    (
        "infra",
        re.compile(
            r"(^|/)(infra|terraform|\.github|docker|deploy|scripts/aws)(/|$)|\.tf$|Dockerfile|docker-compose|\.ya?ml$"
        ),
    ),
    (
        "writing",
        re.compile(
            r"(^|/)(\.lavish|docs?|ai_specs|ai_plans|guides)(/|$)|\.md$|README|CLAUDE\.md|AGENTS\.md|DESIGN\.md"
        ),
    ),
    (
        "building",
        re.compile(
            r"(^|/)(src|app|frontend|lib|packages|api|cli)(/|$)|\.(py|ts|tsx|js|jsx|go|rs|sql|css|html)$"
        ),
    ),
]

_CMD_RULES: list[tuple[Class, re.Pattern[str]]] = [
    (
        "evals",
        re.compile(
            r"\b(pytest|vitest|npm test|uv run (ruff|mypy)|ruff|mypy|eval|benchmark|tsc --noEmit|typecheck)\b"
        ),
    ),
    (
        "infra",
        re.compile(
            r"\b(terraform|docker|aws |gh (workflow|run|api)|launchd|launchctl|kubectl|npm run build|npm ci|uv sync)\b"
        ),
    ),
    ("writing", re.compile(r"\b(lavish-axi|\.lavish/|\.md\b)")),
    (
        "building",
        re.compile(r"\b(uv run (python|pt|src)|npm run dev|node |python3? -m|npx |cargo|go run)\b"),
    ),
    (
        "review",
        re.compile(
            r"^\s*(git (status|log|diff|show|branch)|ls|cat|head|tail|grep|rg|find|wc|sed -n)\b"
        ),
    ),
]
_PATHISH = re.compile(r"(?<![\w-])((?:[\w.-]+/)+[\w.-]+\.[a-z]{1,5})\b")

_EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
_READ_TOOLS = {"Read", "Grep", "Glob", "LS", "WebFetch", "WebSearch"}


def classify_path(path: str) -> Class:
    for cls, rx in _RULES:
        if rx.search(path):
            return cls
    return "unknown"


def classify_command(command: str) -> tuple[Class, list[str]]:
    """Class of a shell command plus the file paths it mentions. The command
    text itself is never stored — only its class and the paths."""
    paths = _PATHISH.findall(command)[:10]
    for cls, rx in _CMD_RULES:
        if rx.search(command):
            return cls, paths
    votes = Counter(classify_path(p) for p in paths)
    votes.pop("unknown", None)
    return (votes.most_common(1)[0][0] if votes else "unknown"), paths


def classify(
    tools: Iterable[str], paths: Iterable[str], command_classes: Iterable[Class] = ()
) -> Class:
    """Majority class of the paths touched and commands run; falls back on the tool mix."""
    tools = list(tools)
    votes = Counter(classify_path(p) for p in paths)
    votes.update(c for c in command_classes)
    votes.pop("unknown", None)
    if votes:
        return votes.most_common(1)[0][0]
    if tools and not (set(tools) & _EDIT_TOOLS) and (set(tools) & _READ_TOOLS):
        return "review"
    return "unknown"
