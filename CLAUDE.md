# CLAUDE.md

## Project

**productivity-tracker** — a personal developer-productivity observatory. It
captures what one developer (Nathan) actually does across coding agents,
GitHub, AWS and bespoke artefacts, stores it as an event stream, and presents
it as a web app for reviewing productivity over time.

Sources it is meant to ingest (see `ai_specs/plan_v1.md` for the full design):

- **Coding agents** — Claude Code (`~/.claude/projects/**/*.jsonl`) and Codex
  (`~/.codex/sessions/**/*.jsonl`): tokens, cost, model, project, session
  shape, tool mix, and a *building vs evals* classification.
- **GitHub** — branches, commits, PRs, CI runs, deployments (webhooks + backfill).
- **AWS** — App Runner services, deploy events, cost per project.
- **Bespoke** — lavish pages generated (`.lavish/sNN_*.html` in every repo),
  eval runs, no-mistakes gate runs.

The public demo deployment (App Runner, like `transcript-rag-agent`) serves an
**aggregate-only** snapshot — no prompt text, no transcript content, ever.

## Instructions for Claude

- Read `README.md`, `AGENTS.md` and `ai_specs/plan_v1.md` before making changes.
- Keep implementations scoped to the requested task; prefer boring, testable modules.
- Every collector is **pull-first and idempotent**: re-running it must never
  duplicate events. Events carry a deterministic `event_id`.
- Raw prompts and transcripts never leave the machine. Collectors emit metadata
  only (counts, tokens, paths, hashes, classifications).
- Keep secrets out of source control. Use environment variables; the demo
  image holds no keys.
- Document setup, run commands, and new dependencies in `README.md`.
- Never add `.lavish/` to `.gitignore` — review pages are committed.

## Module Boundaries

```text
src/pt/
  collectors/   # one module per source: claude_code, codex, git_local, github, aws, lavish
  schema/       # event model (pydantic) + versioned JSON schema
  store/        # append-only event store (S3/local) + DuckDB rollups
  api/          # FastAPI: /ingest/* (webhooks) and /api/* (read)
  enrich/       # build-vs-eval classifier, cost tables, weekly narrative
  cli.py        # `pt collect`, `pt rollup`, `pt serve`, `pt github install-hooks`
frontend/       # Vite + React + TS dashboard
infra/terraform # bootstrap (OIDC role, buckets) + demo (ECR, App Runner)
tests/          # fixtures are small, anonymised JSONL samples
```

## Testing Expectations

- Add tests for every parser (Claude Code / Codex JSONL, webhook payloads),
  every rollup query, and the classifier.
- Mock GitHub, AWS and LLM calls. Fixtures live in `tests/fixtures/` and are
  scrubbed of real prompt text.
- Deterministic tests for token/cost arithmetic.

## Style

- Python 3.12, `uv`, Ruff, mypy strict. Frontend: TS strict, Vite, React.
- Conventional commits: `feat(collectors): ...`, `fix(api): ...`.
- Match the sibling projects (`transcript-rag-agent`, `data-qa-agent`) for
  infra, CI and Docker conventions.
