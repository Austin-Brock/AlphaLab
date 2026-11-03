"""The Vercel Cron endpoint that starts the daily run."""

import json
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient

from app.api import cron
from app.api.cron import DispatchError, get_cron_secret, get_daily_run_dispatcher
from app.config import get_settings
from app.main import app

SECRET = "test-cron-secret"
AUTHORIZED = {"Authorization": f"Bearer {SECRET}"}
REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def calls():
    """Records dispatches instead of calling GitHub."""
    made: list[bool] = []
    app.dependency_overrides[get_cron_secret] = lambda: SECRET
    app.dependency_overrides[get_daily_run_dispatcher] = lambda: lambda: made.append(True)
    yield made
    app.dependency_overrides.clear()


@pytest.mark.parametrize("path", ["/cron/daily-run", "/api/cron/daily-run"])
def test_correct_secret_starts_the_run(calls, path):
    response = TestClient(app).get(path, headers=AUTHORIZED)
    assert (response.status_code, response.json()) == (200, {"status": "started"})
    assert calls == [True]


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer wrong"}, {"Authorization": f"Basic {SECRET}"}],
)
def test_wrong_or_missing_secret_starts_nothing(calls, headers):
    assert TestClient(app).get("/cron/daily-run", headers=headers).status_code == 401
    assert calls == []


def test_no_secret_configured_refuses_everything(calls):
    app.dependency_overrides[get_cron_secret] = lambda: None
    for headers in ({}, {"Authorization": "Bearer "}, AUTHORIZED):
        assert TestClient(app).get("/cron/daily-run", headers=headers).status_code == 503
    assert calls == []


def test_dispatch_failure_is_reported(calls):
    def fail():
        raise DispatchError("GitHub returned 403: nope")

    app.dependency_overrides[get_daily_run_dispatcher] = lambda: fail
    response = TestClient(app).get("/cron/daily-run", headers=AUTHORIZED)
    assert response.status_code == 502
    assert "403" in response.json()["detail"]


@pytest.fixture
def github(monkeypatch):
    monkeypatch.setenv("ALPHALAB_GITHUB_DISPATCH_TOKEN", "gh-token")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_dispatch_uses_scheduled_mode_so_it_runs_at_most_once_a_day(github, monkeypatch):
    seen = {}

    def post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return httpx2.Response(204)

    monkeypatch.setattr(cron.httpx2, "post", post)
    cron.dispatch_daily_run()

    assert seen["url"].endswith(
        "/repos/Austin-Brock/AlphaLab/actions/workflows/daily-ai-run.yml/dispatches"
    )
    assert seen["headers"]["Authorization"] == "Bearer gh-token"
    assert seen["json"] == {"ref": "main", "inputs": {"check_only": "false", "scheduled": "true"}}


def test_github_refusal_becomes_a_dispatch_error(github, monkeypatch):
    monkeypatch.setattr(cron.httpx2, "post", lambda *_, **__: httpx2.Response(403, text="nope"))
    with pytest.raises(DispatchError, match="403"):
        cron.dispatch_daily_run()


def test_github_unreachable_becomes_a_dispatch_error(github, monkeypatch):
    def post(*_, **__):
        raise httpx2.ConnectError("down")

    monkeypatch.setattr(cron.httpx2, "post", post)
    with pytest.raises(DispatchError, match="Could not reach GitHub"):
        cron.dispatch_daily_run()


def test_missing_token_becomes_a_dispatch_error(monkeypatch):
    monkeypatch.setenv("ALPHALAB_GITHUB_DISPATCH_TOKEN", "")
    get_settings.cache_clear()
    try:
        with pytest.raises(DispatchError, match="ALPHALAB_GITHUB_DISPATCH_TOKEN"):
            cron.dispatch_daily_run()
    finally:
        get_settings.cache_clear()


def test_vercel_crons_cover_10am_eastern_in_summer_and_winter():
    crons = json.loads((REPO_ROOT / "vercel.json").read_text())["crons"]
    assert {c["path"] for c in crons} == {"/api/cron/daily-run"}
    assert {c["schedule"] for c in crons} == {"5 14 * * 1-5", "5 15 * * 1-5"}
