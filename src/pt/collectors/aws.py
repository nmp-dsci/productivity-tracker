"""AWS: daily cost by project tag (Cost Explorer), App Runner services and
their deploy operations (pull), and the EventBridge payload parser for the
push path (`/ingest/aws`).

Cost Explorer needs the `project` cost-allocation tag activated in Billing;
until then costs group by service and carry project=None.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import boto3

from pt.config import Settings
from pt.schema import Event, Source, event_id, utc
from pt.state import State

SOURCE: Source = "aws"


def parse_eventbridge(payload: dict[str, Any]) -> Iterator[Event]:
    """App Runner "Service Operation Status Change" and ECR "Image Action"."""
    detail = payload.get("detail") or {}
    ts = payload.get("time") or datetime.now(tz=UTC).isoformat()
    if payload.get("source") == "aws.apprunner":
        name = detail.get("serviceName") or ""
        yield Event(
            event_id=event_id(
                SOURCE, "apprunner_deploy", detail.get("operationId") or payload.get("id")
            ),
            source=SOURCE,
            kind="apprunner_deploy",
            ts=utc(ts),
            project=name.removesuffix("-demo") or None,
            cls="infra",
            meta={
                "service": name,
                "status": detail.get("operationStatus"),
                "operation": detail.get("operationType"),
                "region": payload.get("region"),
            },
        )
    elif payload.get("source") == "aws.ecr" and detail.get("action-type") == "PUSH":
        repo = detail.get("repository-name") or ""
        yield Event(
            event_id=event_id(SOURCE, "ecr_push", repo, detail.get("image-digest")),
            source=SOURCE,
            kind="ecr_push",
            ts=utc(ts),
            project=repo.removesuffix("-demo") or None,
            cls="infra",
            meta={
                "repository": repo,
                "tag": detail.get("image-tag"),
                "status": detail.get("result"),
            },
        )


def cost_events(settings: Settings, days: int) -> Iterator[Event]:
    ce = boto3.client("ce", region_name="us-east-1")  # Cost Explorer is global
    end = datetime.now(tz=UTC).date()
    start = end - timedelta(days=days)
    kwargs: dict[str, Any] = {
        "TimePeriod": {"Start": start.isoformat(), "End": end.isoformat()},
        "Granularity": "DAILY",
        "Metrics": ["UnblendedCost"],
        "GroupBy": [{"Type": "TAG", "Key": "project"}, {"Type": "DIMENSION", "Key": "SERVICE"}],
    }
    while True:
        resp = ce.get_cost_and_usage(**kwargs)
        for day in resp.get("ResultsByTime", []):
            d = day["TimePeriod"]["Start"]
            for g in day.get("Groups", []):
                tag, service = g["Keys"]
                project = tag.split("$", 1)[1] if "$" in tag else None
                amount = float(g["Metrics"]["UnblendedCost"]["Amount"])
                if amount == 0:
                    continue
                yield Event(
                    event_id=event_id(SOURCE, "daily_cost", d, tag, service),
                    source=SOURCE,
                    kind="daily_cost",
                    ts=utc(d + "T00:00:00+00:00"),
                    project=project or None,
                    cost_usd=round(amount, 4),
                    cls="infra",
                    meta={"service": service[:60]},
                )
        token = resp.get("NextPageToken")
        if not token:
            break
        kwargs["NextPageToken"] = token


def apprunner_events(settings: Settings) -> Iterator[Event]:
    ar = boto3.client("apprunner", region_name=settings.aws_region)
    for svc in ar.list_services().get("ServiceSummaryList", []):
        name = svc["ServiceName"]
        project = name.removesuffix("-demo")
        yield Event(
            event_id=event_id(
                SOURCE,
                "apprunner_service",
                svc["ServiceArn"],
                svc["Status"],
                svc["UpdatedAt"].date().isoformat(),
            ),
            source=SOURCE,
            kind="apprunner_service",
            ts=utc(svc["UpdatedAt"]),
            project=project,
            cls="infra",
            meta={
                "service": name,
                "status": svc["Status"],
                "url": f"https://{svc.get('ServiceUrl', '')}",
            },
        )
        for op in ar.list_operations(ServiceArn=svc["ServiceArn"], MaxResults=20).get(
            "OperationSummaryList", []
        ):
            yield Event(
                event_id=event_id(SOURCE, "apprunner_deploy", op["Id"]),
                source=SOURCE,
                kind="apprunner_deploy",
                ts=utc(op.get("EndedAt") or op["StartedAt"]),
                project=project,
                cls="infra",
                meta={"service": name, "status": op["Status"], "operation": op["Type"]},
            )


def collect(settings: Settings, state: State, days: int = 30) -> Iterator[Event]:
    yield from cost_events(settings, days)
    yield from apprunner_events(settings)
    state.set("aws_collected_at", datetime.now(tz=UTC).isoformat())
