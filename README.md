# AlphaLab

A simulated autonomous trading bot platform.

AlphaLab starts an AI-managed portfolio with **$1,000,000 in simulated cash** and lets it trade autonomously against **real market data** — researching stocks, proposing trades, managing risk, and explaining every decision — while you watch its performance on a dashboard.

**Live:** https://alphalab-austin.vercel.app

> **Status:** Milestones 1–4 complete (Portfolio Foundation, Market Data, Trading Engine, AI Trading Agent). Milestone 5 in progress: the dashboard, pause/resume and the scheduled daily run are built. See the full [development plan](docs/PLAN.md).

## The dashboard

Anyone can view the live dashboard. It shows, for each portfolio:

- **Value and total return** against the starting capital, and how the money is allocated
- **Value over time,** day by day, from the first trade, next to what the same money would be worth simply held in SPY (an S&P 500 fund)
- **Positions** with unrealized gains and losses
- **AI decisions:** every run's summary, each proposed trade with the AI's reasoning and what the risk engine did with it, and the full record of what the AI looked at
- **Trade history,** including every risk check on every order

The site is read-only for visitors. Only the owner can change anything — placing orders, running the AI, switching auto-trade on or off, or pausing trading.

## How it works

```
AI Strategy (AWS Bedrock) → Trade Proposals → Risk Engine → Execution Engine → Portfolio Ledger
```

The AI **proposes**; the risk and execution engines **decide**. Portfolio accounting knows nothing about AI, so any future strategy (momentum, mean reversion, buy-and-hold) plugs into the same pipeline.

### The AI

Each run, the model reviews the portfolio and the watchlist with four tools — see the portfolio, get latest prices, get price history, and propose a trade. It must look at a stock's price history before it can propose trading it, and it can make at most 5 proposals per run. Proposals are never executed by the AI: each one becomes an ordinary order that goes through the risk engine.

Every run is stored in full: the portfolio snapshot the AI saw, the model and prompt version, the complete conversation including every tool call, and each proposal linked to the order it became.

### Risk checks

Every order passes through the risk engine before anything moves. Orders that break a limit are **rejected, never resized**, and every check result is stored with the order.

| Check | Rule |
| --- | --- |
| Portfolio active | Portfolio isn't paused or closed |
| Market open | US market is open (holidays included) |
| Price available | A fresh price exists for the symbol |
| No short selling | Can only sell shares held |
| Sufficient cash | Order cost ≤ available cash |
| Cash reserve | ≥ 5% of the portfolio stays in cash |
| Position concentration | No single stock > 10% of the portfolio |

Approved orders fill at the latest market price plus 0.05% slippage (buys pay more, sells receive less), with no commission. A submitted order can never fill twice.

### Daily runs

Portfolios with **auto-trade** switched on are traded automatically once each trading day, around 10am US Eastern, by a scheduled GitHub Actions job. Each portfolio runs at most once a day; weekends, market holidays and paused portfolios are skipped. Every run appears on the dashboard like any other.

### Pause and resume

Pausing a portfolio is the trading brake: every order is rejected and AI runs are skipped until it's resumed, including orders from an AI run already in progress. Every pause and resume is recorded with its time and reason.

## Stack

- **Backend:** Python, FastAPI, SQLAlchemy, PostgreSQL
- **AI:** AWS Bedrock (currently `openai.gpt-oss-120b`; any tool-using Bedrock model works)
- **Market data:** Alpaca
- **Frontend:** React + TypeScript
- **Hosting:** Vercel, with Neon Postgres

## Running it locally

Requires Docker, [uv](https://docs.astral.sh/uv/), and Node.js 20+.

```bash
docker compose up -d --wait          # Postgres (dev + test databases)
cd backend
cp .env.example .env                 # then fill in your own values
uv sync
uv run alembic upgrade head          # create the schema
uv run python -m app.seed            # create the $1M AlphaLab AI Portfolio
uv run uvicorn app.main:app --reload # API at http://localhost:8000, docs at /docs
```

Start the dashboard (with the API running):

```bash
cd frontend
npm install
npm run dev                          # http://localhost:5173
```

Run the tests:

```bash
cd backend && uv run pytest
cd frontend && npm test && npm run build
```

The API's interactive docs at `/docs` list every endpoint. Money is returned as decimal strings, never floats.

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
