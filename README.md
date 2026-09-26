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
| Screen time | hours the display was on (this Mac), as macOS Screen Time counts them | `pmset -g log` on every collect (~7 days of history); `pt screen-backfill` reads Apple's own store (~30 days of retention) |

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

Keep it fresh: `scripts/install_launchd.sh` installs two LaunchAgents —
`pt collect && pt rollup` (and `pt sync push` when `PT_S3_BUCKET` is set)
every 5 minutes, plus `pt refresh` checked every 30 minutes. `pt refresh`
re-reads every source from the top, re-walks GitHub and AWS, and rebuilds the
rollups once per UTC day (a 30-minute check beats a fixed local hour, which
would drift with DST); it no-ops for the rest of that day, and a missing AWS
credential or GitHub token only warns, never fails the run.

Enrichment (optional, `uv sync --group enrich`). Bills the **Claude subscription**
when `CLAUDE_CODE_OAUTH_TOKEN` is set (via the Claude Agent SDK), otherwise
`ANTHROPIC_API_KEY`; force one with `PT_LLM_BACKEND=subscription|api`:

```bash
uv run pt tag           # tier-2 classifier for sessions tier 1 left unknown (metadata only)
uv run pt weekly        # rolling 7-day narrative → data/narratives/rolling-<date>.md → home page (launchd refreshes daily)
uv run pt weekly --week 2026-09-08   # a calendar-week review → /api/weekly
```

### Screen time

`pt collect` parses `pmset -g log` every run, which needs no permissions but
only reaches back about a week. To seed the history from Apple's own Screen
Time store, grant **Full Disk Access** to your terminal (System Settings →
Privacy & Security → Full Disk Access), then:

```bash
uv run pt screen-backfill            # display spans from ~/Library/.../knowledgeC.db
uv run pt rollup
```

Events carry a start and a duration only — never an app name, window title or
URL. Spans crossing local midnight are split so each belongs to one local day;
dark wakes and any span over 16 hours (a missed "off") are dropped.

The two readers measure the same hours, so they are **never summed**: they are
stored under different kinds (`display_span`, `display_span_apple`) and
`screen_hours` reads Apple's `display_span_apple` events only — pmset spans
are still collected and stored as a permission-less record and cross-check,
but never counted, with no fallback to them on any day. That's deliberate: if
Full Disk Access is ever lost, the metric goes quiet rather than silently
degrading to pmset's ~40%-higher reading (pmset counts the display being lit
while the Mac is locked). If the screen-time strip flatlines, check Full Disk
Access before anything else. Apple keeps roughly **30 days** (measured
2026-09-21: 29 days of `/display/isBacklit`), so the event store is the only
record of anything older — which is why the backfill runs on every tick
rather than once: the launchd job re-runs `pt screen-backfill --days 3` on
every tick so recent days keep Apple's reading.

**Full Disk Access is per-process, and the launchd job is a different process
from your terminal.** Granting it to Terminal or iTerm lets *you* run
`pt screen-backfill`; it does nothing for `com.nmp-dsci.pt-collect`, which
keeps exiting 0 while logging `cannot read …/knowledgeC.db` and the metric
quietly stops at the last day you backfilled by hand. Grant Full Disk Access
to the binary launchd runs (`/bin/sh`, and if that is not enough the uv-managed
interpreter that `readlink -f .venv/bin/python` prints), then confirm with
`pt status` — not by reading the log.

### Is it up to date?

```bash
uv run pt status
```

The single answer to "is this thing still working". It prints the last day
carrying an event for every source and kind, when the daily full refresh last
ran, whether both LaunchAgents are actually loaded, and whether Apple's Screen
Time store is readable **from this process**. It exits non-zero when something
needs a human, so it works from a timer as well as by hand.

It reports a problem when any of these is true, each of which has actually
happened:

| Symptom | What it means |
|---|---|
| a LaunchAgent is not loaded | nothing is collecting at all — re-run `scripts/install_launchd.sh` |
| the full refresh stamp is older than yesterday | the `pt-refresh` agent is not firing (yesterday's stamp is normal for the first half-hour of a UTC day) |
| screen time more than a day behind | the backfill is not reaching `knowledgeC.db`, almost always Full Disk Access |

Being registered is not the same as running: on 2026-09-24 both agents were
found unloaded two days after a successful `launchctl load`, with every source
silently stale. The installer now uses `launchctl bootstrap` and verifies each
label afterwards, and `pt status` checks the agents rather than trusting them.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `PT_DATA_DIR` | `data` | events + rollups |
| `PT_STATE_DIR` | `~/.pt` | collector offsets |
| `PT_REPO_ROOTS` | `~/git/nmp-ai-portfolio:~/git/nmp-projects:~/git` | path → project mapping, in priority order |
| `PT_TZ` | `Australia/Sydney` | day bucketing |
| `PT_PMSET_LOG` | – | read a recorded `pmset -g log` instead of shelling out |
| `PT_KNOWLEDGE_DB` | `~/Library/Application Support/Knowledge/knowledgeC.db` | Screen Time store for `pt screen-backfill` |
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
