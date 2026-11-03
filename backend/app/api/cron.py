"""Endpoints called by Vercel Cron.

Vercel Cron starts the daily run on time, because GitHub's own scheduler has been
hours late. The run itself still happens in GitHub Actions: an agent session is too
long for this endpoint, and AWS access is set up there.

Vercel Cron can only send GET, so this GET is protected by its own secret. Vercel
sends `Authorization: Bearer <CRON_SECRET>`. With no secret set, it refuses every
request (fail closed).
"""

import secrets
from collections.abc import Callable
from typing import Annotated

import httpx2
from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.config import get_settings

router = APIRouter(prefix="/cron", tags=["cron"])

DAILY_RUN_WORKFLOW = "daily-ai-run.yml"


class DispatchError(Exception):
    """GitHub didn't accept the request to start the workflow."""


def get_cron_secret() -> str | None:
    secret = get_settings().cron_secret
    return secret.get_secret_value() if secret else None


def require_cron_secret(
    request: Request, cron_secret: Annotated[str | None, Depends(get_cron_secret)]
) -> None:
    if not cron_secret:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "CRON_SECRET is not set.")
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(
        token.encode(), cron_secret.encode()
    ):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid cron secret.")


def dispatch_daily_run() -> None:
    """Start the workflow in scheduled mode, which runs each portfolio at most once a day."""
    settings = get_settings()
    if not settings.github_dispatch_token:
        raise DispatchError("ALPHALAB_GITHUB_DISPATCH_TOKEN is not set")
    try:
        response = httpx2.post(
            f"https://api.github.com/repos/{settings.github_repo}"
            f"/actions/workflows/{DAILY_RUN_WORKFLOW}/dispatches",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {settings.github_dispatch_token.get_secret_value()}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            json={"ref": "main", "inputs": {"check_only": "false", "scheduled": "true"}},
            timeout=10.0,
        )
    except httpx2.TransportError as exc:
        raise DispatchError(f"Could not reach GitHub: {exc}") from exc
    if not response.is_success:
        raise DispatchError(f"GitHub returned {response.status_code}: {response.text[:200]}")


def get_daily_run_dispatcher() -> Callable[[], None]:
    return dispatch_daily_run


@router.get("/daily-run", dependencies=[Depends(require_cron_secret)])
def start_daily_run(
    dispatch: Annotated[Callable[[], None], Depends(get_daily_run_dispatcher)],
) -> dict[str, str]:
    try:
        dispatch()
    except DispatchError as exc:
        # Vercel doesn't retry, so this shows up in its cron logs. GitHub's own
        # schedule remains as the backup for the day.
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    return {"status": "started"}
