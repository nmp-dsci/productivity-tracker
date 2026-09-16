# AGENTS.md

## Project Context

`productivity-tracker` turns a developer's exhaust — agent sessions, git
activity, deployments, generated review pages — into a reviewable
productivity timeline. Design of record: `ai_specs/plan_v1.md`
(rendered for review in `.lavish/s00_implementation-plan.html`).

Current status: **built** (branch `init`): collectors, rollups, API, frontend,
infra and enrichment run end to end. See `README.md` for commands.

## Working Guidelines

- Keep changes small and easy to inspect.
- Collectors are pull-first (read local files / APIs), idempotent, and emit
  the versioned event schema in `src/pt/schema/`. Webhooks are an accelerator,
  never the only path — backfill must always be possible.
- Privacy is a hard constraint: metadata only. If a field could contain prompt
  or transcript text, hash it or drop it.
- Do not add databases, queues or services the plan does not call for. The
  target architecture is S3 event store + DuckDB + one App Runner service.
- Update `README.md` when commands or setup change.
- Every visual review goes through `/lavish` into `.lavish/` with the next
  `sNN_` prefix; those pages are committed and are themselves a tracked metric.

## Expected Architecture Direction

```text
src/pt/collectors/*   one module per source, pull-first, idempotent (event_id)
src/pt/store/         local JSONL store, S3 mirror, DuckDB rollups (queries/*.sql)
src/pt/api/           FastAPI: queries.py over parquet, app.py routes + demo redaction
src/pt/enrich/        prices.yaml, tier-1 classify, tier-2 tagger, weekly narrative
frontend/src/         views/*.tsx, ui/index.tsx, styles/tokens.css (DESIGN.md)
infra/terraform/      bootstrap (bucket, OIDC role, EventBridge) + demo (ECR, App Runner)
```

Gotchas learned from the real data — keep them true:

- Claude Code writes one line per content block with the same `message.id`
  and `usage`; fold per message or tokens are 2–3× overcounted.
- Transcripts are purged after 30 days; `history.jsonl` is the durable source
  for sessions and prompts. Never make it the source for tokens.
- `cwd` can be a scratchpad (`/private/tmp/claude-*/<slug>/…`) or a
  no-mistakes worktree (`~/.no-mistakes/worktrees/<gate>/…`); both resolve
  in `Settings.project_from_path`.
- Labels from `pt tag` are events (`kind = label`); rollups prefer them.

## Quality Bar

- Parsers: fixture-driven tests, one fixture per real-world file shape seen.
- Rollups: SQL lives in `src/pt/store/queries/*.sql`, tested against a tiny
  DuckDB built from fixtures.
- CI: lint, type-check, tests, and a frontend build — mirror
  `transcript-rag-agent/.github/workflows/ci.yml`.

## Agent Notes

- Start with `README.md`, this file, then `ai_specs/plan_v1.md`.
- The demo deployment pattern to copy is
  `../transcript-rag-agent/infra/terraform/{bootstrap,demo}` and its
  `Dockerfile` (single read-only container, image baked with a snapshot,
  no secrets, OIDC deploy from GitHub Actions).
- `nmp-dsci` is a GitHub **user** account, not an org — webhooks are per-repo.
