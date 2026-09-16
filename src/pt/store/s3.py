"""Mirror `data/` to and from S3, same layout. Objects are immutable per day
file except the current day's, which is re-uploaded when its size changes."""

from __future__ import annotations

import boto3
from botocore.exceptions import ClientError
from mypy_boto3_s3 import S3Client

from pt.config import Settings


def _client(settings: Settings) -> S3Client:
    return boto3.client("s3", region_name=settings.aws_region)


def _bucket(settings: Settings) -> str:
    if not settings.s3_bucket:
        raise RuntimeError("PT_S3_BUCKET is not set")
    return settings.s3_bucket


def push(settings: Settings) -> int:
    s3 = _client(settings)
    bucket = _bucket(settings)
    n = 0
    for sub in ("events", "rollups"):
        base = settings.data_dir / sub
        for path in sorted(base.glob("**/*")):
            if not path.is_file():
                continue
            key = str(path.relative_to(settings.data_dir))
            size = path.stat().st_size
            try:
                head = s3.head_object(Bucket=bucket, Key=key)
                if head["ContentLength"] == size:
                    continue
            except ClientError:
                pass
            s3.upload_file(str(path), bucket, key)
            n += 1
    return n


def pull(settings: Settings) -> int:
    s3 = _client(settings)
    bucket = _bucket(settings)
    n = 0
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if not (key.startswith("events/") or key.startswith("rollups/")):
                continue
            target = settings.data_dir / key
            if target.exists() and target.stat().st_size == obj["Size"]:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, key, str(target))
            n += 1
    return n


def put_events(settings: Settings, source: str, day: str, lines: list[str]) -> str | None:
    """Ingest path: append-only by writing one small immutable object per
    batch, so multiple App Runner instances never contend on a file."""
    if not settings.s3_bucket:
        return None
    import time

    key = f"events/{source}/{day}.{int(time.time() * 1000)}.jsonl"
    _client(settings).put_object(Bucket=settings.s3_bucket, Key=key, Body="\n".join(lines) + "\n")
    return key
