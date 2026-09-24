from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from pt.collectors import github
from pt.collectors.aws import parse_eventbridge
from pt.collectors.github import parse_webhook
from pt.config import Settings
from pt.state import State


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


def test_backfill_deployments_survive_unsorted_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # The deployments endpoint is not requested with an explicit sort, so a
    # recent deployment can appear after an older one in the page. Backfill
    # must not stop at the first older item, or it would silently drop it.
    deployments = [
        {"id": 1, "created_at": "2020-01-01T00:00:00Z", "ref": "main", "environment": "production"},
        {"id": 2, "created_at": "2026-09-10T00:00:00Z", "ref": "main", "environment": "production"},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/user/repos":
            return httpx.Response(200, json=[{"full_name": "nmp-dsci/alpha"}])
        if path.endswith("/pulls"):
            return httpx.Response(200, json=[])
        if path.endswith("/actions/runs"):
            return httpx.Response(200, json={"workflow_runs": []})
        if path == "/repos/nmp-dsci/alpha/deployments":
            return httpx.Response(200, json=deployments)
        if path == "/repos/nmp-dsci/alpha/deployments/1/statuses":
            return httpx.Response(200, json=[])
        if path == "/repos/nmp-dsci/alpha/deployments/2/statuses":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 100,
                        "state": "success",
                        "created_at": "2026-09-10T00:05:00Z",
                        "environment_url": "https://example.com",
                    }
                ],
            )
        raise AssertionError(f"unexpected request: {path}")

    monkeypatch.setattr(
        github,
        "client",
        lambda: httpx.Client(base_url=github.API, transport=httpx.MockTransport(handler)),
    )

    settings = Settings(github_owner="nmp-dsci")
    state = State(tmp_path / "state.json")
    events = list(github.backfill(settings, state, days=30))

    statuses = [e for e in events if e.kind == "deployment_status"]
    assert len(statuses) == 1
    assert statuses[0].meta["status"] == "success"
