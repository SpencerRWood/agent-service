import asyncio
import hashlib
import hmac

import httpx

from app.features.orchestration.models import ProviderName
from app.features.orchestration.schemas import (
    PullRequestState,
    WorkerExecutionResult,
    WorkerTarget,
)
from app.integrations.github.client import (
    GitHubPullRequestStateClient,
    GitHubWebhookEvent,
    GitHubWebhookVerifier,
)


class RunStub:
    repo = "agent-service"
    pr_number = 42
    provider = ProviderName.CODEX
    execution_result_json = WorkerExecutionResult(
        provider="codex",
        worker_target=WorkerTarget.WORKER_B,
        branch_name="feature/test",
        commit_shas=["abc123"],
        pr_title="PR",
        pr_body="Body",
        pr_url="https://github.com/example/agent-service/pull/42",
        pr_number=42,
        execution_summary="done",
    ).model_dump(mode="json")


def test_github_pr_state_client_returns_approved_state():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/pulls/42"):
            return httpx.Response(200, json={"number": 42, "state": "open", "merged": False})
        if request.url.path.endswith("/pulls/42/reviews"):
            return httpx.Response(
                200,
                json=[
                    {"state": "COMMENTED", "user": {"login": "reviewer-a"}},
                    {"state": "APPROVED", "user": {"login": "reviewer-b"}},
                ],
            )
        raise AssertionError(f"Unexpected path: {request.url.path}")

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport, base_url="https://api.github.test")
    client = GitHubPullRequestStateClient(
        owner="example",
        token="token",
        base_url="https://api.github.test",
        client=http_client,
    )

    state = asyncio.run(client.get_state(RunStub()))

    assert state == PullRequestState(
        status="approved", approved_by=["reviewer-b"], source="github_api"
    )
    assert calls == [
        "/repos/example/agent-service/pulls/42",
        "/repos/example/agent-service/pulls/42/reviews",
    ]


def test_github_pr_state_client_returns_merged_state():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/pulls/42")
        return httpx.Response(
            200,
            json={
                "number": 42,
                "state": "closed",
                "merged": True,
                "merged_at": "2026-04-01T16:00:00Z",
            },
        )

    transport = httpx.MockTransport(handler)
    http_client = httpx.AsyncClient(transport=transport, base_url="https://api.github.test")
    client = GitHubPullRequestStateClient(
        owner="example",
        token="token",
        base_url="https://api.github.test",
        client=http_client,
    )

    state = asyncio.run(client.get_state(RunStub()))

    assert state.status == "merged"
    assert state.merged_at is not None


def test_github_webhook_event_maps_review_payload():
    event = GitHubWebhookEvent.from_request(
        event_name="pull_request_review",
        payload={
            "action": "submitted",
            "repository": {"name": "agent-service"},
            "pull_request": {"number": 42},
            "review": {"state": "approved", "user": {"login": "reviewer-b"}},
        },
    )

    assert event is not None
    assert event.status == "approved"
    assert event.repo == "agent-service"
    assert event.pr_number == 42
    assert event.approved_by == ["reviewer-b"]


def test_github_webhook_verifier_accepts_valid_signature():
    secret = "top-secret"
    body = b'{"zen":"testing"}'
    signature = (
        "sha256="
        + hmac.new(
            secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).hexdigest()
    )

    GitHubWebhookVerifier(secret=secret).verify(body, signature)
