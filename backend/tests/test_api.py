import uuid


def create(client, **overrides):
    body = {
        "name": "AlphaLab AI Portfolio",
        "starting_capital": "1000000.00",
        "strategy_id": "ai-trading-v1",
    } | overrides
    response = client.post("/portfolios", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_milestone_1_definition_of_done(client):
    """Query the API and get back $1,000,000 in cash and zero holdings."""
    portfolio_id = create(client)["id"]

    summary = client.get(f"/portfolios/{portfolio_id}").json()
    assert summary["name"] == "AlphaLab AI Portfolio"
    assert summary["status"] == "ACTIVE"
    assert summary["cash"] == "1000000.0000"
    assert summary["positions_value"] == "0"
    assert summary["total_value"] == "1000000.0000"

    assert client.get(f"/portfolios/{portfolio_id}/positions").json() == []
    assert client.get(f"/portfolios/{portfolio_id}/cash").json()["cash"] == "1000000.0000"


def test_ledger_and_value_endpoints(client):
    portfolio_id = create(client)["id"]

    [entry] = client.get(f"/portfolios/{portfolio_id}/ledger").json()
    assert entry["entry_type"] == "DEPOSIT"
    assert entry["amount"] == "1000000.0000"

    value = client.get(f"/portfolios/{portfolio_id}/value").json()
    assert value["total_value"] == "1000000.0000"
    assert value["positions"] == []


def test_list_portfolios(client):
    a = create(client, name="A")["id"]
    b = create(client, name="B", starting_capital="250000")["id"]
    ids = [p["id"] for p in client.get("/portfolios").json()]
    assert a in ids and b in ids


def test_unknown_portfolio_returns_404(client):
    response = client.get(f"/portfolios/{uuid.uuid4()}")
    assert response.status_code == 404


def test_rejects_invalid_starting_capital(client):
    for bad in ["0", "-5", "abc", "1.123456"]:
        response = client.post(
            "/portfolios",
            json={"name": "X", "starting_capital": bad, "strategy_id": "ai-trading-v1"},
        )
        assert response.status_code == 422, bad
