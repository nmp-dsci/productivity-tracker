# AGENTS.md

## Project Context

`productivity-tracker` turns a developer's exhaust — agent sessions, git
activity, deployments, generated review pages — into a reviewable
productivity timeline. Design of record: `ai_specs/plan_v1.md`
(rendered for review in `.lavish/s00_implementation-plan.html`).

Current status: **scaffold** (branch `init`). No source code yet.

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
laptop                      cloud (ap-southeast-2)
──────                      ──────────────────────
pt collect ──► events ──►  S3 events bucket ──► DuckDB rollups ──► FastAPI /api ──► React UI
  claude_code                ▲                                       ▲
  codex                      │ POST /ingest/github (HMAC)            │ demo image bakes
  git_local        GitHub webhooks (per-repo)                        │ a parquet snapshot
  lavish           EventBridge → App Runner deploy events            │
  aws (cost, apprunner)
```

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
