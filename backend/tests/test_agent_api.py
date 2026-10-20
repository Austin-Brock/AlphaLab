import uuid

from tests.fakes import final, history, propose, tool_call


def create_portfolio(client, strategy_id: str = "ai-trading-v1") -> str:
    return client.post(
        "/portfolios",
        json={"name": "AI", "starting_capital": "1000000", "strategy_id": strategy_id},
    ).json()["id"]


def test_milestone_4_definition_of_done(client, fake_llm):
    """Trigger a run: the AI proposes, the risk engine approves, the simulator fills."""
    pid = create_portfolio(client)
    fake_llm.turns = [
        tool_call("get_portfolio"),
        history("AAPL"),
        propose("AAPL", "BUY", 100, "Strong recent momentum", n=1),
        final("Opened an AAPL position."),
    ]

    response = client.post(f"/portfolios/{pid}/agent-runs", json={})

    assert response.status_code == 201, response.text
    run = response.json()
    assert run["status"] == "COMPLETED"
    assert run["summary"] == "Opened an AAPL position."
    [decision] = run["decisions"]
    assert decision["rationale"] == "Strong recent momentum"
    assert decision["order"]["status"] == "FILLED"
    assert decision["order"]["source"] == "ai-trading-v1"
    assert decision["order"]["execution"]["price"] == "100.0500"
    assert run["input_snapshot"]["cash"] == "1000000.0000"
    assert run["transcript"][0]["role"] == "user"

    [position] = client.get(f"/portfolios/{pid}/positions").json()
    assert (position["symbol"], position["quantity"]) == ("AAPL", "100.000000")


def test_run_history_and_lookup(client, fake_llm):
    pid = create_portfolio(client)
    fake_llm.turns = [final("Held.")]
    run_id = client.post(f"/portfolios/{pid}/agent-runs").json()["id"]

    [summary] = client.get(f"/portfolios/{pid}/agent-runs").json()
    assert summary["id"] == run_id
    assert "transcript" not in summary  # list view stays small
    assert client.get(f"/portfolios/{pid}/agent-runs/{run_id}").json()["transcript"]
    assert client.get(f"/portfolios/{pid}/agent-runs/{uuid.uuid4()}").status_code == 404


def test_run_key_returns_existing_run(client, fake_llm):
    pid = create_portfolio(client)
    fake_llm.turns = [final("Held.")]
    first = client.post(f"/portfolios/{pid}/agent-runs", json={"run_key": "daily:2026-10-20"})
    second = client.post(f"/portfolios/{pid}/agent-runs", json={"run_key": "daily:2026-10-20"})
    assert first.json()["id"] == second.json()["id"]


def test_manual_portfolio_cannot_run_the_agent(client):
    pid = create_portfolio(client, strategy_id="manual")
    response = client.post(f"/portfolios/{pid}/agent-runs")
    assert response.status_code == 422
    assert "ai-trading-v1" in response.json()["detail"]
