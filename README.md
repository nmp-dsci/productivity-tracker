# productivity-tracker

A personal developer-productivity observatory: one place to see what I built,
how much agent effort it took, and what actually shipped — across coding
agents, GitHub, AWS and the review pages generated along the way.

> Status: **scaffold**. The design is in [`ai_specs/plan_v1.md`](ai_specs/plan_v1.md);
> the review page is `.lavish/s00_implementation-plan.html`.

## What it tracks

| Source | Signals | Capture |
|---|---|---|
| Claude Code | tokens (input/output/cache), model, project, branch, session length, tool mix, build vs eval | local collector over `~/.claude/projects/**/*.jsonl` + hooks for live events |
| Codex | same, from `~/.codex/sessions/**/*.jsonl` | local collector |
| Git / GitHub | branches, commits, PRs, reviews, CI runs, deployments | per-repo webhooks + API backfill + local reflog scan |
| AWS | App Runner services & deploys, ECR pushes, cost per project | Cost Explorer + EventBridge + tag scan |
| Lavish pages | pages generated per project (`.lavish/sNN_*.html`) | local filesystem scan |
| Evals / gates | eval runs, no-mistakes gate outcomes | local scan of `evals/runs`, `~/.no-mistakes` |

## Architecture (target)

Local collectors → append-only event store (S3) → DuckDB rollups → FastAPI →
React dashboard, deployed as a single read-only App Runner service (same
pattern as `transcript-rag-agent`). The public demo serves aggregate metrics
only; raw prompts never leave the laptop.

## Development

```bash
uv sync                      # once src/ exists
uv run pt collect --all      # pull local sources into ./data/events/
uv run pt rollup             # build DuckDB/parquet rollups
uv run pt serve              # FastAPI + built frontend on :8080
```

## Licence

MIT — see [LICENSE](LICENSE).
