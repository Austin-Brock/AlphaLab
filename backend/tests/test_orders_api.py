import uuid


def create_portfolio(client) -> str:
    return client.post(
        "/portfolios",
        json={"name": "Manual", "starting_capital": "1000000", "strategy_id": "manual"},
    ).json()["id"]


def test_milestone_3_definition_of_done(client):
    """Manually buy 100 shares and verify the cash balance and position quantity."""
    pid = create_portfolio(client)

    response = client.post(
        f"/portfolios/{pid}/orders", json={"symbol": "aapl", "side": "BUY", "quantity": 100}
    )

    assert response.status_code == 201
    order = response.json()
    assert order["status"] == "FILLED"
    assert order["symbol"] == "AAPL"
    assert order["source"] == "manual"
    assert len(order["risk_checks"]) == 7
    # Fake AAPL price is $100; +0.05% slippage.
    assert order["execution"]["price"] == "100.0500"
    assert order["execution"]["gross_amount"] == "10005.0000"

    assert client.get(f"/portfolios/{pid}/cash").json()["cash"] == "989995.0000"
    [position] = client.get(f"/portfolios/{pid}/positions").json()
    assert position == {"symbol": "AAPL", "quantity": "100.000000", "average_cost": "100.0500"}


def test_rejected_order_returns_reasons(client):
    pid = create_portfolio(client)
    # Fake AAPL is $100, so 1,000 shares is ~10%: over the limit after slippage.
    order = client.post(
        f"/portfolios/{pid}/orders", json={"symbol": "AAPL", "side": "BUY", "quantity": 1000}
    ).json()
    assert order["status"] == "REJECTED"
    assert order["execution"] is None
    assert "limit 10.0%" in order["rejection_reason"]
    failed = [c["check_name"] for c in order["risk_checks"] if not c["passed"]]
    assert failed == ["position_concentration"]


def test_duplicate_client_order_id_returns_original_with_200(client):
    pid = create_portfolio(client)
    body = {"symbol": "AAPL", "side": "BUY", "quantity": 10, "client_order_id": "run-1"}
    first = client.post(f"/portfolios/{pid}/orders", json=body)
    second = client.post(f"/portfolios/{pid}/orders", json=body)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]
    assert len(client.get(f"/portfolios/{pid}/executions").json()) == 1


def test_order_history_and_lookup(client):
    pid = create_portfolio(client)
    a = client.post(
        f"/portfolios/{pid}/orders", json={"symbol": "AAPL", "side": "BUY", "quantity": 1}
    ).json()
    b = client.post(
        f"/portfolios/{pid}/orders", json={"symbol": "MSFT", "side": "SELL", "quantity": 1}
    ).json()

    history = client.get(f"/portfolios/{pid}/orders").json()
    assert [o["id"] for o in history] == [b["id"], a["id"]]  # newest first
    assert client.get(f"/portfolios/{pid}/orders/{a['id']}").json()["status"] == "FILLED"
    assert client.get(f"/portfolios/{pid}/orders/{uuid.uuid4()}").status_code == 404


def test_portfolio_shows_risk_limits(client):
    pid = create_portfolio(client)
    body = client.get(f"/portfolios/{pid}").json()
    assert (body["max_position_pct"], body["min_cash_pct"]) == ("0.1000", "0.0500")


def test_order_validation(client):
    pid = create_portfolio(client)
    for bad in [
        {"symbol": "AAPL", "side": "BUY", "quantity": 0},
        {"symbol": "AAPL", "side": "BUY", "quantity": 1.5},
        {"symbol": "AAPL", "side": "HOLD", "quantity": 1},
        {"symbol": "AA PL", "side": "BUY", "quantity": 1},
    ]:
        assert client.post(f"/portfolios/{pid}/orders", json=bad).status_code == 422, bad


def test_orders_for_unknown_portfolio_404(client):
    response = client.post(
        f"/portfolios/{uuid.uuid4()}/orders", json={"symbol": "AAPL", "side": "BUY", "quantity": 1}
    )
    assert response.status_code == 404


def test_amounts_are_formatted_without_excess_decimals(client):
    pid = create_portfolio(client)
    client.post(
        f"/portfolios/{pid}/orders", json={"symbol": "AAPL", "side": "BUY", "quantity": 100}
    )

    value = client.get(f"/portfolios/{pid}/value").json()
    assert value["positions_value"] == "10000.0000"
    assert value["total_value"] == "999995.0000"

    oversell = client.post(
        f"/portfolios/{pid}/orders", json={"symbol": "AAPL", "side": "SELL", "quantity": 101}
    ).json()
    assert oversell["rejection_reason"] == "Cannot sell 101 AAPL: only 100 held"
