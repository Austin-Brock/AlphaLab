import uuid
from decimal import Decimal

import pytest

from app.models import PortfolioStatus
from app.services.portfolio import PortfolioClosedError, PortfolioService
from tests.fakes import final, history, propose


def create_portfolio(client, strategy_id: str = "manual") -> str:
    return client.post(
        "/portfolios",
        json={"name": "P", "starting_capital": "1000000", "strategy_id": strategy_id},
    ).json()["id"]


def buy(client, pid: str, quantity: int = 10) -> dict:
    return client.post(
        f"/portfolios/{pid}/orders", json={"symbol": "AAPL", "side": "BUY", "quantity": quantity}
    ).json()


def test_paused_portfolio_rejects_orders_until_resumed(client):
    pid = create_portfolio(client)

    paused = client.post(f"/portfolios/{pid}/pause", json={"reason": "Reviewing the AI"})
    assert paused.status_code == 200
    assert paused.json()["status"] == "PAUSED"

    order = buy(client, pid)
    assert order["status"] == "REJECTED"
    assert order["rejection_reason"] == "Portfolio is PAUSED"
    assert client.get(f"/portfolios/{pid}/cash").json()["cash"] == "1000000.0000"

    assert client.post(f"/portfolios/{pid}/resume").json()["status"] == "ACTIVE"
    assert buy(client, pid)["status"] == "FILLED"


def test_status_changes_are_recorded_newest_first(client):
    pid = create_portfolio(client)
    client.post(f"/portfolios/{pid}/pause", json={"reason": "Reviewing the AI"})
    client.post(f"/portfolios/{pid}/resume")

    changes = client.get(f"/portfolios/{pid}/status-changes").json()
    assert [(c["from_status"], c["to_status"], c["reason"]) for c in changes] == [
        ("PAUSED", "ACTIVE", None),
        ("ACTIVE", "PAUSED", "Reviewing the AI"),
    ]


def test_pausing_twice_is_a_no_op(client):
    pid = create_portfolio(client)
    client.post(f"/portfolios/{pid}/pause")
    assert client.post(f"/portfolios/{pid}/pause").json()["status"] == "PAUSED"
    assert len(client.get(f"/portfolios/{pid}/status-changes").json()) == 1


def test_unknown_portfolio(client):
    assert client.post(f"/portfolios/{uuid.uuid4()}/pause").status_code == 404


def test_closed_portfolio_cannot_be_paused_or_resumed(client, session):
    pid = create_portfolio(client)
    portfolio = PortfolioService(session).get_portfolio(uuid.UUID(pid))
    portfolio.status = PortfolioStatus.CLOSED
    session.commit()

    for action in ("pause", "resume"):
        response = client.post(f"/portfolios/{pid}/{action}")
        assert response.status_code == 409
        assert "closed" in response.json()["detail"]
    with pytest.raises(PortfolioClosedError):
        PortfolioService(session).resume(portfolio.id)


def test_paused_portfolio_skips_agent_runs_without_calling_the_model(client, fake_llm):
    pid = create_portfolio(client, "ai-trading-v1")
    client.post(f"/portfolios/{pid}/pause")
    fake_llm.turns = [final("should not be called")]

    run = client.post(f"/portfolios/{pid}/agent-runs").json()

    assert run["status"] == "SKIPPED"
    assert run["summary"] == "Portfolio is paused"
    assert fake_llm.calls == []


def test_pause_during_an_agent_run_blocks_its_orders(client, session, fake_llm):
    """Pausing while the model is thinking still stops its trades: the risk engine re-checks."""
    pid = create_portfolio(client, "ai-trading-v1")
    pause_after = fake_llm.converse

    def converse(*args, **kwargs):
        response = pause_after(*args, **kwargs)
        if len(fake_llm.calls) == 2:  # after the proposal, before the model finishes
            PortfolioService(session).pause(uuid.UUID(pid), "Stop!")
        return response

    fake_llm.converse = converse
    fake_llm.turns = [history("AAPL"), propose("AAPL", "BUY", 10), final("Bought AAPL.")]

    run = client.post(f"/portfolios/{pid}/agent-runs").json()

    [decision] = run["decisions"]
    assert decision["order"]["status"] == "REJECTED"
    assert decision["order"]["rejection_reason"] == "Portfolio is PAUSED"
    assert client.get(f"/portfolios/{pid}/cash").json()["cash"] == "1000000.0000"
    assert Decimal(client.get(f"/portfolios/{pid}/value").json()["positions_value"]) == 0
