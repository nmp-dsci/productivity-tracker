"""Weekly narrative: a short review drafted from the rollups — never from
prompts — and saved to data/narratives/<week>.md for /api/weekly."""

from __future__ import annotations

import json
from datetime import date, timedelta

from pt.api import queries as q
from pt.config import Settings
from pt.enrich.llm import Completer, completer, narrative_model

SYSTEM = """You write a developer's weekly review from their own productivity metrics.
Voice: second person, plain, specific, no cheerleading. 180-260 words in 3 short paragraphs:
1. What shipped (merged PRs, deploys, pages, eval runs) and where effort went (tokens/$ by project and class).
2. What changed vs the prior week, with the numbers.
3. One or two things worth a look: a project that consumed tokens without commits, a build:eval ratio drifting, an unusually expensive day.
Use the data literally; if something is zero or missing, say so rather than inventing. Markdown, no headings, no bullet lists."""


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def run(settings: Settings, week: str | None = None, complete: Completer | None = None) -> str:
    d = date.fromisoformat(week) if week else date.today() - timedelta(days=7)
    start = week_start(d)
    con = q.open_db(settings.rollups_dir)
    data = q.overview(con, start)
    con.close()
    payload = {
        "week": f"{data['week_start']} to {data['week_end']}",
        "kpis": {k: round(v, 2) for k, v in data["kpis"].items()},
        "prior_week": {k: round(v, 2) for k, v in data["prior"].items()},
        "by_project": data["projects"][:10],
        "tokens_by_class": data["split"],
        "shipped": [
            {"day": s["day"], "kind": s["kind"], "project": s["project"], "title": s["title"]}
            for s in data["shiplog"][:25]
        ],
    }
    complete = complete or completer(narrative_model())
    text = complete(SYSTEM, json.dumps(payload, default=str), max_tokens=1200).strip()
    out = settings.data_dir / "narratives" / f"{start.isoformat()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n")
    return f"wrote {out} ({len(text.split())} words)"
