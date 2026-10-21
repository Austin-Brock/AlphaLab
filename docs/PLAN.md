# AlphaLab — Development Plan

Build one autonomous AI trading bot first, but design the underlying architecture so AlphaLab can eventually support multiple portfolios, strategies, and simulations without a rewrite.

The key distinction is **building for extensibility** vs. **building features we don't need yet**. We don't need a multi-strategy platform today — we just need to avoid architectural decisions that would prevent one later.

---

## 1. Version 1: One AI Trading Bot, $1 Million

The application starts with $1,000,000 in simulated cash and autonomously manages a portfolio using real market data.

The AI will:

1. Research stocks using market data.
2. Decide which securities to purchase.
3. Submit simulated trades.
4. Monitor existing positions.
5. Decide whether to buy, sell, or hold.
6. Track portfolio performance.
7. Explain its investment decisions.

A dashboard shows its performance over time.

### V1 scope

| Feature                | V1          |
| ---------------------- | ----------- |
| Starting capital       | $1,000,000  |
| Portfolios             | 1           |
| AI trading strategies  | 1           |
| Market data            | Real prices |
| Simulated trades       | Yes         |
| Autonomous trading     | Yes         |
| Portfolio dashboard    | Yes         |
| Risk management        | Yes         |
| Trading history        | Yes         |
| AI decision history    | Yes         |
| Multiple simulations   | Later       |
| Strategy comparisons   | Later       |
| Historical backtesting | Later       |

---

## 2. Architecture Decisions for Future Expansion

### Decision 1: Give the portfolio a unique ID

Even with only one portfolio, never hardcode it. Create a portfolio record:

```python
portfolio = {
    "id": "portfolio-001",
    "name": "AlphaLab AI Portfolio",
    "starting_capital": "1000000.00",
    "strategy_id": "ai-trading-v1",
    "status": "ACTIVE",
}
```

Every trade, position, and AI decision references this portfolio. Adding another portfolio later is then straightforward — no database restructuring.

### Decision 2: Separate the strategy from the trading engine

The AI is **not** the trading engine. The AI is a *strategy* that produces trade proposals; the trading engine handles execution.

```python
from abc import ABC, abstractmethod


class TradingStrategy(ABC):
    @abstractmethod
    async def generate_proposals(self, portfolio, market_data):
        ...


class AITradingStrategy(TradingStrategy):
    async def generate_proposals(self, portfolio, market_data):
        # Research securities using an LLM
        # Analyze existing positions
        # Return proposed trades
        ...
```

Later strategies (`MomentumStrategy`, `MeanReversionStrategy`, `BuyAndHoldStrategy`, …) return the same standardized trade-proposal format, so new strategies never require changes to the execution engine.

### Decision 3: Make portfolio accounting independent of AI

The portfolio service has no knowledge of AWS Bedrock, Strands Agents, or LLMs. Its only job is maintaining accurate financial records.

```python
class PortfolioService:
    def get_portfolio(self, portfolio_id): ...
    def get_positions(self, portfolio_id): ...
    def get_cash_balance(self, portfolio_id): ...
    def calculate_portfolio_value(self, portfolio_id): ...
```

This lets any future strategy reuse the portfolio infrastructure.

---

## 3. V1 Architecture

```
                   React Dashboard
                          |
                          v
                       FastAPI
                          |
          +---------------+---------------+
          |               |               |
          v               v               v
      Portfolio        Trading         Analytics
       Service         Service          Service
          |               |               |
          +---------------+---------------+
                          |
                      PostgreSQL

                  Celery Scheduler
                          |
                          v
                     AI Strategy  <-->  AWS Bedrock
                          |
                          v
                    Trade Proposal
                          |
                          v
                     Risk Engine
                          |
                          v
                  Execution Engine
                          |
                          v
                    Portfolio DB
```

---

## 4. Database Design (V1)

| Table                 | Purpose                                      |
| --------------------- | -------------------------------------------- |
| `portfolios`          | Portfolio configuration and starting capital |
| `positions`           | Current holdings                             |
| `orders`              | Simulated buy/sell orders                    |
| `executions`          | Completed simulated trades                   |
| `cash_ledger`         | Financial transactions                       |
| `agent_runs`          | AI execution history                         |
| `agent_decisions`     | AI recommendations and reasoning             |
| `portfolio_snapshots` | Historical portfolio performance             |

Every table storing portfolio-specific data includes a `portfolio_id`.

### Not building yet

- A `simulations` table
- A strategy management interface
- A multi-portfolio dashboard
- A strategy comparison engine
- A strategy marketplace
- A complex orchestration system

When multiple simulations arrive, a `simulations` table can reference portfolios and strategy configurations.

---

## 5. Implementation Roadmap

| # | Milestone              | Deliverable                                          |
| - | ---------------------- | ---------------------------------------------------- |
| 1 | Portfolio Foundation   | $1M simulated portfolio with accurate accounting     |
| 2 | Market Data            | Live price updates and historical price retrieval    |
| 3 | Trading Engine         | Simulated orders, risk checks, execution history     |
| 4 | AI Trading             | Autonomous trade proposals using AWS Bedrock         |
| 5 | Dashboard & Automation | Scheduled trading and portfolio monitoring           |

### Milestone 1 — Portfolio Foundation

- Create a portfolio with $1,000,000.
- Store its starting capital.
- Track cash balances.
- Track positions.
- Record financial transactions.
- Calculate portfolio value.

**Done when:** the API returns a portfolio containing $1,000,000 in cash and zero holdings.

### Milestone 2 — Market Data

- Retrieve current stock prices.
- Retrieve historical candles.
- Track when market data was last updated.
- Handle API failures.
- Cache market data.

**Done when:** prices for 10 selected securities can be retrieved and displayed.

### Milestone 3 — Trading Engine

**Risk policy (decided):** max 10% of the portfolio in one stock, min 5% cash, orders that break a limit are rejected (never resized), market hours enforced.

- Submit buy/sell orders.
- Validate available cash.
- Enforce risk constraints.
- Calculate simulated execution prices.
- Update positions.
- Record executions.
- Prevent duplicate fills.

**Done when:** you can manually buy 100 shares of a stock and verify the resulting cash balance and position quantity.

### Milestone 4 — AI Trading Agent

Introduce AWS Bedrock. *(Built on the Bedrock Converse API directly rather than Strands: the tool loop is small, and owning it makes every prompt, tool call, and result straightforward to record. The model is `openai.gpt-oss-120b` for now; it is a config change to swap in another Bedrock model such as Claude once Anthropic model access is enabled on the account.)*

- Give the AI access to portfolio information.
- Give it access to market data.
- Allow it to research stocks.
- Generate structured trade proposals.
- Validate proposals through the risk engine.
- Record explanations for every decision.

**Done when:** the AI independently proposes a trade that the backend validates and executes in the simulator.

### Milestone 5 — Dashboard & Automation

- Display portfolio value.
- Display current positions.
- Display trade history.
- Display AI decisions.
- Schedule daily trading evaluations.
- Allow trading to be paused and resumed.

**Done when:** the application runs autonomously during market hours while its decisions are monitored through the dashboard.

> **Progress:** The dashboard (React + TypeScript, Vite, in `frontend/`) covers the four display items. Pause/resume is built: paused portfolios reject every order and skip agent runs, every change is audited, and the dashboard has the switch. Scheduling runs as a GitHub Actions workflow (free, no server): portfolios opt in with an auto-trade switch, the job runs on weekday mornings at 10:00 ET at most once per day, and it reaches Bedrock through GitHub OIDC with a role limited to model invocation, so no AWS keys are stored. The public website itself has no AWS access. Portfolio value is shown as of now; a value-over-time chart needs either stored daily snapshots or a replay of the ledger against daily closes.

---

## 6. How AlphaLab Evolves

| Version                         | New capabilities                                         |
| ------------------------------- | -------------------------------------------------------- |
| V1 — AI Trading Bot             | One AI strategy managing $1M                             |
| V1.1 — Configurable Capital     | Create fresh portfolios with different starting balances |
| V2 — Multiple Simulations       | Run independent portfolios simultaneously                |
| V2.1 — Multiple Strategies      | AI, momentum, mean reversion, buy-and-hold               |
| V2.2 — Strategy Comparison      | Compare performance, risk, and trading behavior          |
| V3 — Historical Backtesting     | Replay strategies against historical market conditions   |

V1 code should already have reusable strategy, portfolio, risk, and execution interfaces; future features are implemented only when needed.

---

## 7. Reproducible Trading Decisions

Even in V1, record enough to reconstruct *why* the AI made each decision. For every AI evaluation, store:

- Portfolio holdings at decision time
- Available cash
- Market data snapshot
- AI model identifier
- Prompt version
- Research inputs
- Trade proposals
- Risk validation results
- Final execution outcome

If the AI sells AAPL, we should be able to inspect exactly what information it had at the time. This also makes later strategy comparisons far more meaningful, and demonstrates auditability and operational resilience.

---

## 8. Stack

| Layer           | Choice                                      |
| --------------- | ------------------------------------------- |
| Backend         | Python, FastAPI, SQLAlchemy, PostgreSQL     |
| AI              | AWS Bedrock (Converse API)                  |
| Market data     | Alpaca                                      |
| Frontend        | React + TypeScript                          |
| Background jobs | Celery + Redis                              |
| Deployment      | Docker Compose (initially)                  |

## 9. Engineering Rules

1. **No hardcoded portfolio IDs.** Every portfolio operation accepts an ID.
2. **No AI-controlled execution.** The AI proposes; the risk and execution engines decide.
3. **No direct balance mutations.** Portfolio balances derive from recorded financial transactions.
4. **No strategy-specific trading logic.** Strategies generate proposals through a shared interface.

---

## 10. Open Questions / Review Notes

Items to resolve before or during the relevant milestone:

- ~~**Positions vs. Rule 3.**~~ `positions` is updated only by the execution engine, and a test verifies it always equals a replay of `executions`.
- ~~**Money types.**~~ `NUMERIC`/`Decimal` everywhere, including parsing Alpaca's JSON.
- **Corporate actions.** Stock splits and dividends will silently corrupt positions and P&L unless handled (Milestone 3). Cached bars are split-adjusted as of when they were fetched, so after a split the `price_bars` cache for that symbol must be refetched.
- ~~**Execution realism.**~~ Decided in Milestone 3: fill at the latest trade price ± 5 bps slippage, $0 commission (both configurable).
- ~~**Market calendar.**~~ Milestone 3 uses Alpaca's market clock (handles holidays and half-days) and fails closed if it can't be reached. All timestamps are stored in UTC.
- **Alpaca data tier.** The free tier provides IEX-only real-time data; confirm that's acceptable or budget for SIP.
- **Scheduler weight.** For a single daily evaluation, APScheduler inside the app may be simpler than Celery + Redis; revisit if job volume grows.
- ~~**Idempotency.**~~ Orders are idempotent per `client_order_id`, each order fills at most once, and agent runs are idempotent per `run_key` (for the Milestone 5 scheduler).
- **Research depth.** In the first live run, gpt-oss-120b proposed trades without calling `get_price_history`, so rationales were generic. Resolved for now in prompt `ai-trading-v1.1`: `propose_trade` refuses a symbol until its price history has been pulled in the same session. The check is per symbol, not tied to the watchlist, so it carries over if the tradable universe grows. Prompt iteration and a stronger model remain options.
- **Tradable universe.** The agent trades only the 10 watchlist symbols. Widening it is a config change (`ALPHALAB_WATCHLIST`) but affects research cost per run and how the model picks candidates.
