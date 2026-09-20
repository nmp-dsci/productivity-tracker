# productivity-tracker

A personal developer-productivity observatory: one place to see what I built,
how much agent effort it took, and what actually shipped — across coding
agents, GitHub, AWS and the review pages generated along the way.

> **Status:** built on branch `init` — collectors, rollups, API, frontend,
> infra and enrichment all run end to end on real data. Design of record:
> [`ai_specs/plan_v1.md`](ai_specs/plan_v1.md) · visual system:
> [`DESIGN.md`](DESIGN.md) · review page: `.lavish/s00_implementation-plan.html`.

## What it tracks

| Source | Signals | Capture |
|---|---|---|
| Claude Code | tokens (input/output/cache/thinking), model, project, branch, tool mix, file paths, build / evals / infra / writing / review class | `~/.claude/projects/**/*.jsonl` (offset-tailed) + `~/.claude/history.jsonl` (sessions & prompts; survives the 30-day transcript purge) |
| Codex | tokens, model, project per session | `~/.codex/sessions/**/*.jsonl` |
| Local git | commits (+/- lines, branch via `--source`), branch switches — including branches only pushed to the no-mistakes gate | `git log --all` + reflog for every repo under `PT_REPO_ROOTS` |
| GitHub | PRs opened/merged, reviews, CI runs (conclusion, duration), deployments, releases | per-repo webhooks → `/ingest/github` + `pt github backfill` |
| AWS | App Runner services & deploy operations, ECR pushes, daily cost by `project` tag | `pt aws collect` + EventBridge → `/ingest/aws` |
| Lavish pages | review pages created/updated per project | `**/.lavish/sNN_*.html` |
| Eval runs | run per project with headline metrics | `evals/runs/*.json`, `runs/*/run.json` |
| no-mistakes | gate pushes and pipeline pass/fail | `~/.no-mistakes/logs/daemon.log` |

Every event is one row of the v1 schema (`src/pt/schema.py`) with a
deterministic `event_id`, so every collector is idempotent. **No prompt or
transcript text ever leaves the machine** — `tests/test_privacy.py` scans every
fixture-derived event for it.

Two things the data taught us on day one (both handled):

- Claude Code writes one JSONL line *per content block* with the same
  `usage`; summing per line overcounts tokens 2–3×. Lines are folded per
  `message.id`.
- Claude Code deletes transcripts after `cleanupPeriodDays` (default 30).
  `history.jsonl` survives and backfills sessions/prompts; tokens older than
  30 days are gone. Run the collector every 5 minutes and consider
  `"cleanupPeriodDays": 3650` in `~/.claude/settings.json`.

## Architecture

```text
laptop                                       AWS ap-southeast-2
pt collect (launchd, 5 min) ──► data/events/<source>/<day>.jsonl ──► s3://pt-events-…/events/
                                              │                                │
                                       pt rollup (DuckDB)              rollup.yml (hourly)
                                              ▼                                ▼
                                   data/rollups/*.parquet ◄──────── s3://…/rollups/
                                              │
GitHub webhooks ─► /ingest/github ─┐          ▼
EventBridge ─────► /ingest/aws ────┴─► FastAPI /api/* + React (App Runner; demo image bakes the parquet, PT_DEMO_MODE=1, no keys)
```

Storage is S3 JSONL + DuckDB → parquet (decision D-01); the public demo serves
aggregates only (D-02) — session ids, branches, URLs and paths are stripped.

## Run it locally

```bash
uv sync                                  # Python 3.12 env
uv run pt collect                        # pull every local source (idempotent)
uv run pt github backfill --days 365     # PRs, CI runs, deployments via gh auth
uv run pt rollup                         # DuckDB → data/rollups/{daily,sessions,shiplog}.parquet
(cd frontend && npm ci && npm run build) # React bundle
uv run pt serve --port 8080              # http://127.0.0.1:8080
```

Frontend dev loop: `cd frontend && npm run dev` (proxies `/api` to :8080).

Keep it fresh: `scripts/install_launchd.sh` installs a LaunchAgent that runs
`pt collect && pt rollup` (and `pt sync push` when `PT_S3_BUCKET` is set)
every 5 minutes.

Enrichment (optional, `uv sync --group enrich`). Bills the **Claude subscription**
when `CLAUDE_CODE_OAUTH_TOKEN` is set (via the Claude Agent SDK), otherwise
`ANTHROPIC_API_KEY`; force one with `PT_LLM_BACKEND=subscription|api`:

```bash
uv run pt tag           # tier-2 classifier for sessions tier 1 left unknown (metadata only)
uv run pt weekly        # rolling 7-day narrative → data/narratives/rolling-<date>.md → home page (launchd refreshes daily)
uv run pt weekly --week 2026-09-08   # a calendar-week review → /api/weekly
```

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `PT_DATA_DIR` | `data` | events + rollups |
| `PT_STATE_DIR` | `~/.pt` | collector offsets |
| `PT_REPO_ROOTS` | `~/git/nmp-ai-portfolio:~/git/nmp-projects:~/git` | path → project mapping, in priority order |
| `PT_TZ` | `Australia/Sydney` | day bucketing |
| `PT_GITHUB_OWNER` | `nmp-dsci` | repos to hook and backfill |
| `PT_S3_BUCKET` | – | enables `pt sync` and S3 writes from `/ingest/*` |
| `PT_INGEST_SECRET` | – | GitHub HMAC secret / EventBridge bearer |
| `PT_DEMO_MODE` | `0` | read-only, aggregates only |
| `PT_LLM_BACKEND` | `subscription` if `CLAUDE_CODE_OAUTH_TOKEN` set, else `api` | who pays for `pt tag` / `pt weekly` |
| `PT_TAGGER_MODEL` / `PT_NARRATIVE_MODEL` | `claude-haiku-4-5` / `claude-opus-5` | enrichment models |

## Deploy (AWS)

Same pattern as `transcript-rag-agent`: one read-only App Runner service,
image built by GitHub Actions via OIDC, no stored keys.

1. `aws login`, then once: `cd infra/terraform/bootstrap && terraform init && terraform apply`
   → events bucket `pt-events-<account>`, deploy role, collector policy.
2. `export PT_S3_BUCKET=pt-events-<account>` and `uv run pt sync push`.
3. Merge to `main` → `.github/workflows/deploy-aws.yml` pulls the rollups,
   builds and pushes `pt-demo`, applies `infra/terraform/demo`, smoke-tests.
4. Webhooks: `PT_INGEST_SECRET=… uv run pt github install-hooks https://<service>/ingest/github`
   and re-apply bootstrap with `-var ingest_url=https://<service>/ingest/aws -var ingest_secret=…`
   for EventBridge. `rollup.yml` rebuilds the parquet hourly so webhook events reach the demo.

## Development

```bash
uv run pytest -q          # 21 tests: parsers, idempotency, cost, rollups, API, ingest, demo redaction, privacy
uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy
cd frontend && npm run typecheck && npm test && npm run build
docker build -t pt-demo . && docker run --rm -p 8080:8080 pt-demo   # the demo image, locally
```

## Licence

MIT — see [LICENSE](LICENSE).
