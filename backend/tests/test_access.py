"""Anyone can read; only the owner (admin key) can change anything."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.api.auth import get_admin_key
from app.config import Settings
from app.main import app
from tests.conftest import TEST_ADMIN_KEY

# Every documented endpoint that isn't a read, taken from the app itself, so a new
# write endpoint is covered by these tests automatically.
WRITE_ROUTES = sorted(
    (method.upper(), path)
    for path, operations in app.openapi()["paths"].items()
    for method in operations
    if method.upper() not in {"GET", "HEAD", "OPTIONS"}
)


def test_there_are_write_routes_to_protect():
    assert ("POST", "/portfolios/{portfolio_id}/orders") in WRITE_ROUTES
    assert ("POST", "/portfolios/{portfolio_id}/agent-runs") in WRITE_ROUTES
    assert ("POST", "/portfolios/{portfolio_id}/pause") in WRITE_ROUTES


@pytest.mark.parametrize(("method", "path"), WRITE_ROUTES)
def test_visitors_cannot_call_any_write_route(visitor, method, path):
    response = visitor.request(method, path.replace("{portfolio_id}", str(uuid.uuid4())), json={})
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "authorization",
    ["Bearer wrong-key", f"Basic {TEST_ADMIN_KEY}", TEST_ADMIN_KEY, f"Bearer {TEST_ADMIN_KEY}x"],
)
def test_wrong_or_malformed_keys_are_refused(visitor, authorization):
    response = visitor.post(
        "/portfolios",
        json={"name": "X", "starting_capital": "1000", "strategy_id": "manual"},
        headers={"Authorization": authorization},
    )
    assert response.status_code == 401


def test_visitor_can_read_everything_the_dashboard_shows(client, visitor):
    pid = client.post(
        "/portfolios", json={"name": "P", "starting_capital": "1000000", "strategy_id": "manual"}
    ).json()["id"]
    client.post(f"/portfolios/{pid}/orders", json={"symbol": "AAPL", "side": "BUY", "quantity": 1})

    for path in [
        "/portfolios",
        f"/portfolios/{pid}",
        f"/portfolios/{pid}/value",
        f"/portfolios/{pid}/positions",
        f"/portfolios/{pid}/orders",
        f"/portfolios/{pid}/agent-runs",
        f"/portfolios/{pid}/status-changes",
        "/market/clock",
        "/market/prices",
        "/api/portfolios",
    ]:
        assert visitor.get(path).status_code == 200, path


def test_visitor_cannot_pause_and_nothing_changes(client, visitor):
    pid = client.post(
        "/portfolios", json={"name": "P", "starting_capital": "1000000", "strategy_id": "manual"}
    ).json()["id"]
    assert visitor.post(f"/api/portfolios/{pid}/pause").status_code == 401
    assert visitor.get(f"/portfolios/{pid}").json()["status"] == "ACTIVE"
    assert visitor.get(f"/portfolios/{pid}/status-changes").json() == []


def test_admin_check(client, visitor):
    assert client.get("/admin/check").status_code == 204
    assert visitor.get("/admin/check").status_code == 401


def test_writes_fail_closed_without_a_configured_key(client):
    app.dependency_overrides[get_admin_key] = lambda: None
    response = client.post(
        "/portfolios", json={"name": "X", "starting_capital": "1000", "strategy_id": "manual"}
    )
    assert response.status_code == 503
    assert "ALPHALAB_ADMIN_KEY" in response.json()["detail"]
    assert client.get("/admin/check").status_code == 503


def test_short_admin_keys_are_rejected_at_startup(monkeypatch):
    monkeypatch.setenv("ALPHALAB_ADMIN_KEY", "too-short")
    with pytest.raises(ValueError, match="at least 32"):
        Settings(_env_file=None)


def test_visitors_only_see_watchlist_symbols(client, visitor):
    assert visitor.get("/market/prices", params={"symbols": "AAPL,MSFT"}).status_code == 200
    response = visitor.get("/market/prices", params={"symbols": "AAPL,GME"})
    assert response.status_code == 403
    assert "GME" in response.json()["detail"]
    assert visitor.get("/market/bars/GME").status_code == 403
    # The owner can still look anything up.
    assert client.get("/market/bars/AAPL").status_code == 200


def test_bar_ranges_are_capped(visitor):
    end = datetime(2026, 10, 19, tzinfo=UTC)
    response = visitor.get(
        "/market/bars/AAPL",
        params={
            "timeframe": "1Min",
            "start": (end - timedelta(days=8)).isoformat(),
            "end": end.isoformat(),
        },
    )
    assert response.status_code == 422
    assert "limited to 7 days" in response.json()["detail"]
