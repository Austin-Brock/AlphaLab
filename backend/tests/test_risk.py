from dataclasses import replace
from decimal import Decimal

from app.models import OrderSide, PortfolioStatus
from app.trading.risk import (
    CashReserve,
    MarketOpen,
    NoShortSelling,
    PortfolioActive,
    PositionConcentration,
    ProposedOrder,
    RiskContext,
    RiskEngine,
    SufficientCash,
)
from app.trading.service import simulated_fill_price

MILLION = Decimal("1000000")


def context(price: str = "217.09", side: OrderSide = OrderSide.BUY, **overrides) -> RiskContext:
    market = Decimal(price)
    base = RiskContext(
        portfolio_status=PortfolioStatus.ACTIVE,
        max_position_pct=Decimal("0.10"),
        min_cash_pct=Decimal("0.05"),
        cash=MILLION,
        holdings={},
        valuation_prices={},
        price=market,
        price_problem=None,
        fill_price=simulated_fill_price(market, side, Decimal("5")),
        commission=Decimal("0"),
        market_open=True,
        enforce_market_hours=True,
    )
    return replace(base, **overrides)


def buy(symbol: str, qty: int) -> ProposedOrder:
    return ProposedOrder(symbol, OrderSide.BUY, Decimal(qty))


def sell(symbol: str, qty: int) -> ProposedOrder:
    return ProposedOrder(symbol, OrderSide.SELL, Decimal(qty))


def test_nvda_example_is_rejected_for_concentration():
    """500 NVDA at $217.09 is ~$108.5K, about 10.9% of a $1M portfolio."""
    result = PositionConcentration().evaluate(buy("NVDA", 500), context())
    assert not result.passed
    assert result.message == "NVDA would be 10.9% of portfolio (limit 10.0%)"


def test_order_within_limits_passes_every_check():
    results = RiskEngine().evaluate(buy("NVDA", 400), context())
    assert all(r.passed for r in results), results
    assert len(results) == 7


def test_concentration_counts_existing_holdings():
    # Already hold $80K of NVDA; adding $43K would make it ~12.3%.
    ctx = context(
        cash=Decimal("920000"),
        holdings={"NVDA": Decimal("368.5")},
        valuation_prices={"NVDA": Decimal("217.09")},
    )
    assert not PositionConcentration().evaluate(buy("NVDA", 200), ctx).passed
    assert PositionConcentration().evaluate(buy("NVDA", 90), ctx).passed


def test_cash_reserve_blocks_spending_below_minimum():
    # Many 10% positions already held: only $60K cash left of ~$1M.
    ctx = context(
        price="100",
        cash=Decimal("60000"),
        holdings={"SPY": Decimal("9400")},
        valuation_prices={"SPY": Decimal("100")},
    )
    result = CashReserve().evaluate(buy("AAPL", 200), ctx)
    assert not result.passed
    assert "minimum 5.0%" in result.message
    assert CashReserve().evaluate(buy("AAPL", 50), ctx).passed


def test_insufficient_cash():
    ctx = context(price="100", cash=Decimal("5000"))
    result = SufficientCash().evaluate(buy("AAPL", 100), ctx)
    assert not result.passed
    assert result.message == "Order costs $10,005.00 but only $5,000.00 is available"


def test_cannot_sell_more_than_held():
    ctx = context(side=OrderSide.SELL, holdings={"AAPL": Decimal("10")})
    assert NoShortSelling().evaluate(sell("AAPL", 10), ctx).passed
    result = NoShortSelling().evaluate(sell("AAPL", 11), ctx)
    assert not result.passed
    assert result.message == "Cannot sell 11 AAPL: only 10 held"


def test_sells_pass_concentration_and_cash_reserve_even_when_over_limit():
    # A position that grew past the limit can always be trimmed.
    ctx = context(
        price="100",
        side=OrderSide.SELL,
        cash=Decimal("10000"),
        holdings={"AAPL": Decimal("9900")},
        valuation_prices={"AAPL": Decimal("100")},
    )
    assert PositionConcentration().evaluate(sell("AAPL", 100), ctx).passed
    assert CashReserve().evaluate(sell("AAPL", 100), ctx).passed


def test_paused_portfolio_is_rejected():
    result = PortfolioActive().evaluate(
        buy("AAPL", 1), context(portfolio_status=PortfolioStatus.PAUSED)
    )
    assert not result.passed
    assert result.message == "Portfolio is PAUSED"


def test_market_hours():
    check = MarketOpen()
    assert check.evaluate(buy("AAPL", 1), context(market_open=True)).passed
    assert check.evaluate(buy("AAPL", 1), context(market_open=False)).message == "Market is closed"
    # Fails closed when the clock can't be reached.
    assert not check.evaluate(buy("AAPL", 1), context(market_open=None)).passed
    assert check.evaluate(
        buy("AAPL", 1), context(market_open=False, enforce_market_hours=False)
    ).passed


def test_missing_price_fails_every_price_dependent_check():
    ctx = replace(context(), price=None, fill_price=None, price_problem="No market price for ZZZZ")
    results = {r.name: r for r in RiskEngine().evaluate(buy("ZZZZ", 1), ctx)}
    assert results["price_available"].message == "No market price for ZZZZ"
    for name in ("sufficient_cash", "cash_reserve", "position_concentration"):
        assert not results[name].passed
        assert results[name].message == "Cannot evaluate without a market price"


def test_engine_reports_every_failure_not_just_the_first():
    ctx = context(portfolio_status=PortfolioStatus.PAUSED, market_open=False)
    failed = [r.name for r in RiskEngine().evaluate(buy("NVDA", 500), ctx) if not r.passed]
    assert failed == ["portfolio_active", "market_open", "position_concentration"]


def test_slippage():
    assert simulated_fill_price(Decimal("100"), OrderSide.BUY, Decimal("5")) == Decimal("100.0500")
    assert simulated_fill_price(Decimal("100"), OrderSide.SELL, Decimal("5")) == Decimal("99.9500")
