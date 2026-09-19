#!/usr/bin/env bash
# Build the demo image for linux/amd64 and push it to ECR as :latest (+ sha).
# Needs data/rollups/*.parquet in the build context (pt rollup, or an S3 pull).
set -euo pipefail
cd "$(dirname "$0")/.."
REGION="${AWS_REGION:-ap-southeast-2}"
ACCOUNT="$(aws sts get-caller-identity --query Account --output text)"
REPO="$ACCOUNT.dkr.ecr.$REGION.amazonaws.com/pt-demo"
SHA="$(git rev-parse --short HEAD)"
[ -f data/rollups/daily.parquet ] || { echo "data/rollups/daily.parquet missing — run pt rollup or pt sync pull" >&2; exit 1; }
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ACCOUNT.dkr.ecr.$REGION.amazonaws.com"
docker buildx build --platform linux/amd64 -t "$REPO:latest" -t "$REPO:$SHA" --push .
echo "pushed $REPO:$SHA (and :latest)"
