from __future__ import annotations

import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.settings import settings
from app.features.orchestration.models import PullRequestStatus
from app.features.orchestration.schemas import PullRequestState
from app.features.orchestration.service import NullPullRequestStateClient, PullRequestStateClient


class GitHubIntegrationError(RuntimeError):
    """Raised when GitHub PR sync cannot fetch or interpret state."""


class GitHubWebhookVerifier:
    def __init__(self, *, secret: str | None) -> None:
        self._secret = secret

    @classmethod
    def from_settings(cls) -> GitHubWebhookVerifier:
        return cls(secret=settings.github_webhook_secret)

    def verify(self, body: bytes, signature_256: str | None) -> None:
        if not self._secret:
            return
        if not signature_256:
            raise ValueError("Missing GitHub webhook signature.")

        expected = (
            "sha256="
            + hmac.new(
                self._secret.encode("utf-8"),
                body,
                hashlib.sha256,
            ).hexdigest()
        )
        if not hmac.compare_digest(expected, signature_256):
            raise ValueError("Invalid GitHub webhook signature.")


@dataclass
class GitHubWebhookEvent:
    event_name: str
    repo: str
    pr_number: int
    status: PullRequestStatus
    approved_by: list[str]
    merged_at: datetime | None = None

    @classmethod
    def from_request(
        cls,
        *,
        event_name: str | None,
        payload: Mapping[str, Any],
    ) -> GitHubWebhookEvent | None:
        if not event_name:
            return None

        if event_name == "pull_request":
            return cls._from_pull_request_event(payload)
        if event_name == "pull_request_review":
            return cls._from_pull_request_review_event(payload)

        return None

    @classmethod
    def _from_pull_request_event(
        cls,
        payload: Mapping[str, Any],
    ) -> GitHubWebhookEvent | None:
        action = str(payload.get("action") or "")
        pull_request = payload.get("pull_request")
        repository = payload.get("repository")
        if not isinstance(pull_request, Mapping) or not isinstance(repository, Mapping):
            return None

        if action == "closed":
            merged = bool(pull_request.get("merged"))
            merged_at = _parse_datetime(pull_request.get("merged_at"))
            status = PullRequestStatus.MERGED if merged else PullRequestStatus.CLOSED
            return cls(
                event_name="pull_request",
                repo=str(repository.get("name") or ""),
                pr_number=int(pull_request.get("number") or 0),
                status=status,
                approved_by=[],
                merged_at=merged_at,
            )

        if action in {"opened", "reopened", "ready_for_review", "synchronize"}:
            return cls(
                event_name="pull_request",
                repo=str(repository.get("name") or ""),
                pr_number=int(pull_request.get("number") or 0),
                status=PullRequestStatus.OPEN,
                approved_by=[],
            )

        return None

    @classmethod
    def _from_pull_request_review_event(
        cls,
        payload: Mapping[str, Any],
    ) -> GitHubWebhookEvent | None:
        review = payload.get("review")
        pull_request = payload.get("pull_request")
        repository = payload.get("repository")
        action = str(payload.get("action") or "")
        if (
            not isinstance(review, Mapping)
            or not isinstance(pull_request, Mapping)
            or not isinstance(repository, Mapping)
        ):
            return None

        review_state = str(review.get("state") or "").lower()
        status_map = {
            "approved": PullRequestStatus.APPROVED,
            "changes_requested": PullRequestStatus.CHANGES_REQUESTED,
        }
        if action == "dismissed":
            status = PullRequestStatus.DISMISSED
        else:
            status = status_map.get(review_state)
        if status is None:
            return None

        user = review.get("user")
        approved_by = (
            [str(user.get("login"))] if isinstance(user, Mapping) and user.get("login") else []
        )
        return cls(
            event_name="pull_request_review",
            repo=str(repository.get("name") or ""),
            pr_number=int(pull_request.get("number") or 0),
            status=status,
            approved_by=approved_by,
        )


class GitHubPullRequestStateClient:
    def __init__(
        self,
        *,
        owner: str,
        token: str,
        base_url: str = "https://api.github.com",
        timeout_seconds: float = 15.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._owner = owner
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._client = client

    @classmethod
    def from_settings(cls) -> PullRequestStateClient:
        if settings.git_provider_name != "github":
            return NullPullRequestStateClient()
        if not settings.github_owner or not settings.github_token:
            return NullPullRequestStateClient()

        return cls(
            owner=settings.github_owner,
            token=settings.github_token,
            base_url=settings.github_api_base_url,
            timeout_seconds=settings.control_hub_timeout_seconds,
        )

    async def get_state(self, run) -> PullRequestState | None:
        if not run.pr_number:
            return None

        pull_request = await self._request(
            "GET",
            f"/repos/{self._owner}/{run.repo}/pulls/{run.pr_number}",
        )
        if not isinstance(pull_request, Mapping):
            raise GitHubIntegrationError("GitHub pull request response was not an object.")

        if bool(pull_request.get("merged")):
            return PullRequestState(
                status=PullRequestStatus.MERGED,
                merged_at=_parse_datetime(pull_request.get("merged_at")),
                source="github_api",
            )

        state = str(pull_request.get("state") or "").lower()
        if state == "closed":
            return PullRequestState(status=PullRequestStatus.CLOSED, source="github_api")

        reviews = await self._request(
            "GET",
            f"/repos/{self._owner}/{run.repo}/pulls/{run.pr_number}/reviews",
        )
        if not isinstance(reviews, list):
            raise GitHubIntegrationError("GitHub reviews response was not a list.")

        latest_by_user: dict[str, str] = {}
        for review in reviews:
            if not isinstance(review, Mapping):
                continue
            user = review.get("user")
            login = (
                str(user.get("login")) if isinstance(user, Mapping) and user.get("login") else None
            )
            review_state = str(review.get("state") or "").upper()
            if login:
                latest_by_user[login] = review_state

        if any(state == "CHANGES_REQUESTED" for state in latest_by_user.values()):
            return PullRequestState(status=PullRequestStatus.CHANGES_REQUESTED, source="github_api")

        approved_by = sorted(
            login for login, review_state in latest_by_user.items() if review_state == "APPROVED"
        )
        if approved_by:
            return PullRequestState(
                status=PullRequestStatus.APPROVED,
                approved_by=approved_by,
                source="github_api",
            )

        return PullRequestState(status=PullRequestStatus.OPEN, source="github_api")

    async def _request(
        self,
        method: str,
        path: str,
    ) -> Any:
        headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {self._token}",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._client is not None:
            response = await self._client.request(method, path, headers=headers)
        else:
            async with httpx.AsyncClient(
                base_url=self._base_url,
                timeout=self._timeout_seconds,
            ) as client:
                response = await client.request(method, path, headers=headers)

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise GitHubIntegrationError(
                f"GitHub request failed with {exc.response.status_code}: {exc.response.text}"
            ) from exc
        return response.json()


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None

    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed
