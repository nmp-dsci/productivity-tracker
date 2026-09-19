#!/usr/bin/env bash
# Smoke-test a running instance: health, trends, and that ingest is absent.
set -euo pipefail
URL="${1:?usage: demo_smoke.sh https://host}"
curl -fsS "$URL/api/health" | grep -q '"ok":true'
curl -fsS "$URL/api/trends?grain=week&window=8" | grep -q '"rows"'
code="$(curl -s -o /dev/null -w '%{http_code}' -X POST "$URL/ingest/github")"
[ "$code" = "404" ] || [ "$code" = "405" ] || { echo "ingest reachable in demo ($code)" >&2; exit 1; }
echo "smoke ok: $URL"
