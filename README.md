# AlphaLab

A simulated autonomous trading bot platform.

AlphaLab starts an AI-managed portfolio with **$1,000,000 in simulated cash** and lets it trade autonomously against **real market data** — researching stocks, proposing trades, managing risk, and explaining every decision — while you watch its performance on a dashboard.

> **Status:** Milestone 1 (Portfolio Foundation) complete. See the full [development plan](docs/PLAN.md).

## Getting started

Requires Docker and [uv](https://docs.astral.sh/uv/).

```bash
docker compose up -d --wait          # Postgres (dev + test databases)
cd backend
uv sync
uv run alembic upgrade head          # create the schema
uv run python -m app.seed            # create the $1M AlphaLab AI Portfolio
uv run uvicorn app.main:app --reload # API at http://localhost:8000, docs at /docs
```

Run the tests (against the `alphalab_test` database):

```bash
cd backend && uv run pytest
```

### API

| Method | Path                         | Returns                                    |
| ------ | ---------------------------- | ------------------------------------------ |
| POST   | `/portfolios`                | Create a portfolio funded by a deposit     |
| GET    | `/portfolios`                | All portfolios                             |
| GET    | `/portfolios/{id}`           | Portfolio with cash, positions, total value |
| GET    | `/portfolios/{id}/positions` | Current holdings                           |
| GET    | `/portfolios/{id}/cash`      | Cash balance (sum of ledger)               |
| GET    | `/portfolios/{id}/ledger`    | Every cash movement                        |
| GET    | `/portfolios/{id}/value`     | Valuation breakdown by position            |

Money is returned as decimal strings, never floats.

## How it works

```
Scheduler → AI Strategy (AWS Bedrock) → Trade Proposal → Risk Engine → Execution Engine → Portfolio Ledger
```

The AI **proposes**; the risk and execution engines **decide**. Portfolio accounting knows nothing about AI, so any future strategy (momentum, mean reversion, buy-and-hold) plugs into the same pipeline.

## Stack

- **Backend:** Python, FastAPI, SQLAlchemy, PostgreSQL
- **AI:** AWS Bedrock + Strands Agents
- **Market data:** Alpaca
- **Frontend:** React + TypeScript
- **Background jobs:** Celery + Redis
- **Deployment:** Docker Compose

## Roadmap

| # | Milestone              | Deliverable                                       |
| - | ---------------------- | ------------------------------------------------- |
| 1 | Portfolio Foundation   | $1M simulated portfolio with accurate accounting  |
| 2 | Market Data            | Live price updates and historical price retrieval |
| 3 | Trading Engine         | Simulated orders, risk checks, execution history  |
| 4 | AI Trading             | Autonomous trade proposals using AWS Bedrock      |
| 5 | Dashboard & Automation | Scheduled trading and portfolio monitoring        |

Beyond V1: configurable capital, multiple simultaneous simulations, multiple strategies, strategy comparison, and historical backtesting.

## Engineering rules

1. **No hardcoded portfolio IDs.** Every portfolio operation accepts an ID.
2. **No AI-controlled execution.** The AI proposes; the risk and execution engines decide.
3. **No direct balance mutations.** Balances derive from recorded financial transactions.
4. **No strategy-specific trading logic.** Strategies generate proposals through a shared interface.

## Disclaimer

AlphaLab trades simulated money only. Nothing here is investment advice.
