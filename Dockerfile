# Demo image: the public read-only deployment.
#
# One container, no database, no secrets. The parquet rollups are baked in at
# build time (data/rollups/, pulled from S3 by the deploy workflow), so what a
# given image serves is exactly what its build says it serves. PT_DEMO_MODE=1
# is set here, not in infra: ingest routes do not exist and every response is
# aggregates-only.
#
#   uv run pt rollup                       # or: aws s3 sync s3://…/rollups data/rollups
#   docker build -t pt-demo .
#   docker run --rm -p 8080:8080 pt-demo   # no env file, no keys

# ── Stage 1: frontend bundle ────────────────────────────────────────────
FROM node:24-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: runtime ────────────────────────────────────────────────────
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-hashes --no-emit-project -o requirements.txt \
    && uv pip install --system -r requirements.txt && rm requirements.txt

COPY src/ src/
RUN uv pip install --system --no-deps .
COPY --from=frontend /build/dist frontend/dist
COPY data/rollups data/rollups

ENV PT_DEMO_MODE=1 \
    PT_DATA_DIR=/app/data \
    PYTHONUNBUFFERED=1

EXPOSE 8080
CMD ["pt", "serve", "--host", "0.0.0.0", "--port", "8080"]
