# Plan: productivity-tracker v1

Status: reviewed 2026-09-16 — D-01/02/03/05/06 decided, D-04 open (see Decisions)
Date: 2026-09-16

## Goal

Capture everything a solo AI-assisted developer produces and consumes — agent
tokens, git activity, deployments, generated review pages — into one event
stream, and present it as a web app that answers: *what did I ship, what did
it cost in agent effort, and how is that trending?*

## Current state (measured 2026-09-16)

- `~/.claude/projects/`: 98 project dirs, 10,776 session JSONL files, 71,631
  assistant messages carrying `usage`. Lifetime: 71.4M output tokens, 8.25B
  cache-read, 318M cache-write, 3.9M uncached input. Models: haiku-4-5 (25k
  msgs), sonnet-5 (16.5k), opus-5 (16.2k), fable-5 (8.6k), fable-5-1 (3k).
- **Retention finding:** Claude Code purges transcripts after 30 days
  (`cleanupPeriodDays` unset → default 30). Transcripts on disk start
  2026-08-13. `~/.claude/history.jsonl` (3,919 prompts since Feb 2026, with
  sessionId/project/timestamp) survives and backfills sessions + prompts;
  tokens older than 30 days are unrecoverable. Raise `cleanupPeriodDays`
  and run the collector every 5 min.
- `~/.codex/sessions/`: 92 session files with `token_count` events.
- `.lavish/` in 15 portfolio repos: 195 review pages.
- GitHub: `nmp-dsci` is a user account (no org webhooks). Some repos only have a
  `no-mistakes` remote, so local git must be a source too.
- AWS: account 089783391188, ap-southeast-2, existing OIDC provider + tfstate
  bucket (`data-qa-tfstate-089783391188`), App Runner demo pattern in
  `transcript-rag-agent`.

## Scope

- Include: collectors for Claude Code, Codex, local git, GitHub, AWS, lavish,
  eval runs; event schema; S3 + DuckDB store; FastAPI read/ingest API; React
  dashboard; App Runner demo; weekly narrative.
- Include: build-vs-eval classification of agent sessions.

## Non-Goals

- Exclude: storing or displaying prompt/transcript text anywhere off-laptop.
- Exclude: team/multi-user support. One developer.
- Exclude: real-time streaming UI. Minute-level freshness is enough.

## Architecture

```text
laptop                                   AWS ap-southeast-2
────────────────────────────────         ─────────────────────────────────────────
pt collect (cron / launchd, 5 min)  ───► s3://pt-events-<acct>/raw/<source>/<date>/*.jsonl
  claude_code   ~/.claude/projects/**                    │
  codex         ~/.codex/sessions/**                     ▼
  git_local     ~/git/**/.git (reflog)          pt rollup (GitHub Action, hourly)
  lavish        ~/git/**/.lavish/*.html                  │  DuckDB → parquet
  evals         ~/git/**/evals/runs/*.json               ▼
  aws           Cost Explorer, App Runner       s3://pt-events-<acct>/rollups/*.parquet
                                                         │
GitHub per-repo webhooks ──► POST /ingest/github ───────►│ (App Runner writes raw too)
EventBridge (App Runner deploy) ──► POST /ingest/aws ───►│
                                                         ▼
                                     App Runner: FastAPI /api/* + React UI
                                     (demo image bakes a parquet snapshot; no keys)
```

## Event schema (v1)

One row per event, JSONL, `event_id = sha256(source, natural_key)`:

```json
{"event_id": "…", "schema": 1, "source": "claude_code", "kind": "assistant_message",
 "ts": "2026-09-15T07:54:11Z", "project": "DABStep-loop", "repo": "nmp-dsci/DABStep-loop",
 "branch": "main", "session_id": "551c…", "model": "claude-haiku-4-5-20251001",
 "tokens": {"input": 10, "output": 506, "cache_read": 30221, "cache_write": 0, "thinking": 247},
 "cost_usd": 0.0032, "tools": ["Bash", "Edit"], "class": "building", "meta": {"version": "2.1.259"}}
```

Kinds by source: `claude_code`: session_start, assistant_message, tool_use,
session_end. `codex`: session_meta, token_count. `git_local`: commit.
`github`: push, branch_created, branch_deleted, pr_opened, pr_merged,
review, workflow_run, deployment_status. `aws`: apprunner_deploy,
ecr_push, daily_cost. `lavish`: page_created, page_updated. `evals`: run.

## Proposed Steps

1. **P1 Collectors + schema** — `pt collect` reads Claude Code / Codex JSONL
   incrementally (file offsets in `~/.pt/state.json`), backfills sessions and
   prompts from `~/.claude/history.jsonl`, local git reflogs, lavish pages,
   eval runs, no-mistakes gate runs. Emits events to `data/events/`. Runs
   every 5 min via launchd. Fixture tests.
2. **P2 Store + rollups** — S3 append; DuckDB SQL in `store/queries/*.sql`
   producing daily/weekly parquet: tokens by project×model×class, cost,
   commits, PRs, deploys, pages. `pt rollup`.
3. **P3 API** — FastAPI `/api/trends?grain=day|week&window=90|26`, `/api/overview`, `/api/agents`, `/api/github`,
   `/api/projects/{name}`, `/api/shiplog`, `/api/weekly`; `/ingest/github`,
   `/ingest/aws` with HMAC verification. Demo mode = read-only.
4. **P4 GitHub** — `pt github install-hooks` creates a webhook on every
   `nmp-dsci` repo; `pt github backfill` walks commits/PRs/runs via the API.
5. **P5 Frontend** — Vite + React + TS. Views: **Trends** (landing: one
   contributions-style heatmap row per metric — sessions, tokens, $, lavish
   pages, commits, PRs, deploys, projects active — rolling 90 days or rolling 26 weeks,
   intensity = volume, log-scaled per row; clicking a cell filters the other
   views), Overview, Agents, GitHub, Projects, Ship log, Weekly review.
6. **P6 AWS + deploy** — copy `transcript-rag-agent` bootstrap/demo terraform
   (rename project `pt`), Dockerfile with baked snapshot, `deploy.yml` via
   OIDC. Cost Explorer collector, EventBridge → `/ingest/aws`.
7. **P7 Enrichment** — build-vs-eval classifier (path/tool heuristics first,
   Haiku tagger second), price table, weekly narrative (Haiku over rollups),
   Claude Code live hooks.

## Decisions (2026-09-16)

| ID | Decision | Answer |
|---|---|---|
| D-01 | Storage | A — S3 JSONL + DuckDB/parquet; no database |
| D-02 | Public demo | aggregates only; demo API never returns session ids, paths, branch names |
| D-03 | GitHub capture | per-repo webhooks via `pt github install-hooks` + REST backfill |
| D-04 | Stack | **open** — Python+FastAPI (copy-able infra) vs TS end-to-end (portfolio story, shared types) |
| D-05 | v1 sources | S-01 … S-08 (eval runs and no-mistakes promoted into P1); S-09, S-10 deferred |
| D-06 | Live hooks | deferred to P7 |

## Risks and Open Questions

- D-04 stack: decided by whether this is also meant as a TS/Node-in-AWS portfolio piece.
- Claude Code hooks add live events but carry no token usage; JSONL remains
  the source of truth for tokens.
- App Runner can run >1 instance; the ingest path must be append-only (S3
  objects, never a local file) so instances never conflict.
- Model price table drifts; keep it in `enrich/prices.yaml` with dates.

## Verification

- `uv run pytest` — parsers, rollups, classifier.
- `uv run pt collect --all && uv run pt rollup && uv run pt serve` — local end to end.
- `terraform plan` clean in `infra/terraform/demo`; `/api/health` green on App Runner.
