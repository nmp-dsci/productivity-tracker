from __future__ import annotations

from pt.collectors.aws import parse_eventbridge
from pt.collectors.github import parse_webhook


def test_workflow_run_and_push_parsers() -> None:
    run = {
        "action": "completed",
        "repository": {"full_name": "nmp-dsci/alpha"},
        "workflow_run": {
            "id": 1,
            "run_attempt": 1,
            "name": "CI",
            "conclusion": "success",
            "event": "push",
            "head_branch": "main",
            "run_started_at": "2026-09-11T00:00:00Z",
            "updated_at": "2026-09-11T00:05:00Z",
            "html_url": "https://github.com/x/actions/runs/1",
        },
    }
    (ev,) = parse_webhook("workflow_run", run)
    assert (
        ev.kind == "workflow_run"
        and ev.meta["seconds"] == 300
        and ev.meta["conclusion"] == "success"
    )
    push = {
        "ref": "refs/heads/main",
        "after": "abc123def456",
        "commits": [{}, {}],
        "repository": {"full_name": "nmp-dsci/alpha"},
        "head_commit": {"timestamp": "2026-09-11T00:00:00+10:00"},
    }
    (ev,) = parse_webhook("push", push)
    assert (
        ev.branch == "main"
        and ev.meta["commits"] == 2
        and ev.ts.isoformat().startswith("2026-09-10T14:00")
    )
    assert list(parse_webhook("star", {})) == []


def test_eventbridge_parser() -> None:
    payload = {
        "source": "aws.apprunner",
        "time": "2026-09-11T01:00:00Z",
        "region": "ap-southeast-2",
        "id": "e1",
        "detail": {
            "serviceName": "pt-demo",
            "operationStatus": "DeploymentCompletedSuccessfully",
            "operationType": "UPDATE_SERVICE",
            "operationId": "op-1",
        },
    }
    (ev,) = parse_eventbridge(payload)
    assert (
        ev.kind == "apprunner_deploy"
        and ev.project == "pt"
        and ev.meta["status"].endswith("Successfully")
    )
