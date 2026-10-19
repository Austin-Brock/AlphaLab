"""Risk engine: deterministic pre-trade checks.

Engineering rule: no AI-controlled execution. Strategies propose orders; these
checks decide. Every check runs on every order (no short-circuit) so a rejection
lists all of its reasons. Orders that break a limit are rejected, never resized.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Protocol

from app.models import OrderSide, PortfolioStatus


@dataclass(frozen=True)
class ProposedOrder:
    symbol: str
    side: OrderSide
    quantity: Decimal


@dataclass(frozen=True)
class RiskContext:
    """Everything the checks need, gathered before evaluation."""

    portfolio_status: PortfolioStatus
    max_position_pct: Decimal
    min_cash_pct: Decimal
    cash: Decimal
    # symbol -> shares held
    holdings: Mapping[str, Decimal]
    # symbol -> price used to value holdings (market price, or cost when unavailable)
    valuation_prices: Mapping[str, Decimal]
    # Market price for the order's symbol; None when no usable price exists.
    price: Decimal | None
    # Why `price` is None, e.g. "no market price for ZZZZ".
    price_problem: str | None
    # Estimated fill price including slippage.
    fill_price: Decimal | None
    commission: Decimal
    market_open: bool | None
    enforce_market_hours: bool

    def portfolio_value(self) -> Decimal:
        positions = sum(
            (qty * self.valuation_prices[symbol] for symbol, qty in self.holdings.items()),
            Decimal("0"),
        )
        return self.cash + positions


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    message: str


@dataclass(frozen=True)
class PostTrade:
    """The portfolio as it would look right after the order fills."""

    cash: Decimal
    position_value: Decimal
    total_value: Decimal


def gross_amount(quantity: Decimal, price: Decimal) -> Decimal:
    """Cash value of a fill, rounded to the cent. Shared with the execution engine."""
    return (quantity * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def post_trade(order: ProposedOrder, ctx: RiskContext) -> PostTrade:
    assert ctx.price is not None and ctx.fill_price is not None
    trade_value = gross_amount(order.quantity, ctx.fill_price)
    held = ctx.holdings.get(order.symbol, Decimal("0"))
    if order.side is OrderSide.BUY:
        cash = ctx.cash - trade_value - ctx.commission
        shares = held + order.quantity
    else:
        cash = ctx.cash + trade_value - ctx.commission
        shares = held - order.quantity
    # Value the traded symbol at the current market price, everything else as before.
    others = sum(
        (
            qty * ctx.valuation_prices[symbol]
            for symbol, qty in ctx.holdings.items()
            if symbol != order.symbol
        ),
        Decimal("0"),
    )
    position_value = shares * ctx.price
    return PostTrade(
        cash=cash, position_value=position_value, total_value=cash + others + position_value
    )


class RiskCheck(Protocol):
    name: str

    def evaluate(self, order: ProposedOrder, ctx: RiskContext) -> CheckResult: ...


def _pct(value: Decimal) -> str:
    return f"{value * 100:.1f}%"


def _shares(value: Decimal) -> str:
    """100.000000 -> "100", 2.500000 -> "2.5"."""
    return f"{value.normalize():f}"


def _money(value: Decimal) -> str:
    return f"${value:,.2f}"


class PortfolioActive:
    name = "portfolio_active"

    def evaluate(self, order: ProposedOrder, ctx: RiskContext) -> CheckResult:
        if ctx.portfolio_status is PortfolioStatus.ACTIVE:
            return CheckResult(self.name, True, "Portfolio is active")
        return CheckResult(self.name, False, f"Portfolio is {ctx.portfolio_status}")


class MarketOpen:
    name = "market_open"

    def evaluate(self, order: ProposedOrder, ctx: RiskContext) -> CheckResult:
        if not ctx.enforce_market_hours:
            return CheckResult(self.name, True, "Market hours not enforced")
        if ctx.market_open is None:
            # Fail closed: if we can't confirm the market is open, don't trade.
            return CheckResult(self.name, False, "Could not confirm the market is open")
        if ctx.market_open:
            return CheckResult(self.name, True, "Market is open")
        return CheckResult(self.name, False, "Market is closed")


class PriceAvailable:
    name = "price_available"

    def evaluate(self, order: ProposedOrder, ctx: RiskContext) -> CheckResult:
        if ctx.price is None:
            return CheckResult(self.name, False, ctx.price_problem or "No market price")
        return CheckResult(self.name, True, f"{order.symbol} market price {_money(ctx.price)}")


class NoShortSelling:
    name = "no_short_selling"

    def evaluate(self, order: ProposedOrder, ctx: RiskContext) -> CheckResult:
        if order.side is OrderSide.BUY:
            return CheckResult(self.name, True, "Not a sell")
        held = ctx.holdings.get(order.symbol, Decimal("0"))
        if order.quantity <= held:
            return CheckResult(
                self.name, True, f"Selling {_shares(order.quantity)} of {_shares(held)} shares held"
            )
        return CheckResult(
            self.name,
            False,
            f"Cannot sell {_shares(order.quantity)} {order.symbol}: only {_shares(held)} held",
        )


class _PriceDependentCheck:
    """Base for checks that need a price; they fail when none is available."""

    name: str

    def evaluate(self, order: ProposedOrder, ctx: RiskContext) -> CheckResult:
        if ctx.price is None or ctx.fill_price is None:
            return CheckResult(self.name, False, "Cannot evaluate without a market price")
        return self.check(order, ctx, post_trade(order, ctx))

    def check(self, order: ProposedOrder, ctx: RiskContext, after: PostTrade) -> CheckResult:
        raise NotImplementedError


class SufficientCash(_PriceDependentCheck):
    name = "sufficient_cash"

    def check(self, order: ProposedOrder, ctx: RiskContext, after: PostTrade) -> CheckResult:
        if after.cash >= 0:
            return CheckResult(self.name, True, f"Cash after trade {_money(after.cash)}")
        cost = ctx.cash - after.cash
        return CheckResult(
            self.name, False, f"Order costs {_money(cost)} but only {_money(ctx.cash)} is available"
        )


class CashReserve(_PriceDependentCheck):
    name = "cash_reserve"

    def check(self, order: ProposedOrder, ctx: RiskContext, after: PostTrade) -> CheckResult:
        if order.side is OrderSide.SELL:
            return CheckResult(self.name, True, "Sells increase cash")
        share = after.cash / after.total_value if after.total_value > 0 else Decimal("0")
        if share >= ctx.min_cash_pct:
            return CheckResult(self.name, True, f"Cash would be {_pct(share)} of portfolio")
        return CheckResult(
            self.name,
            False,
            f"Cash would be {_pct(share)} of portfolio (minimum {_pct(ctx.min_cash_pct)})",
        )


class PositionConcentration(_PriceDependentCheck):
    name = "position_concentration"

    def check(self, order: ProposedOrder, ctx: RiskContext, after: PostTrade) -> CheckResult:
        if order.side is OrderSide.SELL:
            return CheckResult(self.name, True, "Sells reduce concentration")
        share = after.position_value / after.total_value if after.total_value > 0 else Decimal("1")
        if share <= ctx.max_position_pct:
            return CheckResult(
                self.name, True, f"{order.symbol} would be {_pct(share)} of portfolio"
            )
        return CheckResult(
            self.name,
            False,
            f"{order.symbol} would be {_pct(share)} of portfolio "
            f"(limit {_pct(ctx.max_position_pct)})",
        )


DEFAULT_CHECKS: tuple[RiskCheck, ...] = (
    PortfolioActive(),
    MarketOpen(),
    PriceAvailable(),
    NoShortSelling(),
    SufficientCash(),
    CashReserve(),
    PositionConcentration(),
)


class RiskEngine:
    def __init__(self, checks: Sequence[RiskCheck] = DEFAULT_CHECKS):
        self.checks = checks

    def evaluate(self, order: ProposedOrder, ctx: RiskContext) -> list[CheckResult]:
        return [check.evaluate(order, ctx) for check in self.checks]
