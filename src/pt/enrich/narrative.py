"""Narrative: a short review drafted from the rollups — never from prompts.

Default is the rolling window the home page shows (last 7 days vs the 7
before), saved as data/narratives/rolling-<end>.md; `--week` writes a
calendar-week review to <monday>.md for /api/weekly.
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from pt.api import queries as q
from pt.config import Settings
from pt.enrich.llm import Completer, completer, narrative_model

SYSTEM = """You write a developer's review of their last seven days from their own productivity metrics.
Voice: second person, plain, specific, no cheerleading. 180-260 words in 3 short paragraphs:
1. What shipped (merged PRs, deploys, pages, eval runs) and where effort went (tokens/$ by project and class).
2. What changed against the previous seven days, metric by metric, with the numbers — this introduces the
   metrics the reader is about to scroll through, so name them plainly (sessions, prompts, output tokens, cost, pages, commits, PRs, deploys, projects).
3. One or two things worth a look: a project that consumed tokens without commits, a build:eval ratio drifting, an unusually expensive day.
Use the data literally; if something is zero or missing, say so rather than inventing. Markdown, no headings, no bullet lists."""


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _payload(data: dict[str, Any]) -> str:
    return json.dumps(
        {
            "window": f"{data['start']} to {data['end']}",
            "prior_window": f"{data['prior_start']} to {data['prior_end']}",
            "metrics": data["metrics"],
            "by_project": data["projects"][:10],
            "tokens_by_class": data["split"],
            "shipped": [
                {"day": s["day"], "kind": s["kind"], "project": s["project"], "title": s["title"]}
                for s in data["shiplog"][:25]
            ],
        },
        default=str,
    )


def _fresh(path: Path, max_age_hours: float | None) -> bool:
    if not max_age_hours or not path.exists():
        return False
    return (time.time() - path.stat().st_mtime) < max_age_hours * 3600


def run(
    settings: Settings,
    week: str | None = None,
    complete: Completer | None = None,
    max_age_hours: float | None = None,
) -> str:
    con = q.open_db(settings.rollups_dir)
    if week:
        start = week_start(date.fromisoformat(week))
        data = q.overview(con, start)
        out = settings.data_dir / "narratives" / f"{start.isoformat()}.md"
    else:
        # The configured zone, matching the day buckets in the rollups — see
        # the note on `today()` in pt.api.app.
        end = datetime.now(ZoneInfo(settings.timezone)).date()
        data = q.window_summary(con, end - timedelta(days=6), end)
        out = settings.data_dir / "narratives" / f"rolling-{end.isoformat()}.md"
    con.close()
    if _fresh(out, max_age_hours):
        return f"{out} is fresh; skipped"
    complete = complete or completer(narrative_model())
    text = complete(SYSTEM, _payload(data), max_tokens=1200).strip()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n")
    return f"wrote {out} ({len(text.split())} words)"
