"""Order submission and simulated execution.

Flow for every order:
    1. Gather prices and the market clock (before locking, since that may write the price cache).
    2. Lock the portfolio row so concurrent orders can't spend the same cash.
    3. Record the order, run every risk check, and record each result.
    4. Rejected: stop. Approved: fill it, writing the execution, ledger entries,
       and position update in the same transaction as the order.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.market_data.provider import MarketDataUnavailableError
from app.models import (
    CashLedgerEntry,
    Execution,
    LedgerEntryType,
    Order,
    OrderSide,
    OrderStatus,
    Portfolio,
    Position,
    RiskCheckResult,
)
from app.services.market_data import LatestPrices, MarketDataService
from app.services.portfolio import PortfolioNotFoundError, PortfolioService
from app.trading.risk import ProposedOrder, RiskContext, RiskEngine, gross_amount

BPS = Decimal("10000")
PRICE_PLACES = Decimal("0.0001")


@dataclass(frozen=True)
class ExecutionSettings:
    slippage_bps: Decimal = Decimal("5")
    commission_per_order: Decimal = Decimal("0")
    max_price_age: timedelta = timedelta(minutes=5)
    enforce_market_hours: bool = True


@dataclass(frozen=True)
class SubmitResult:
    order: Order
    # False when an order with the same client_order_id already existed.
    created: bool


def simulated_fill_price(market_price: Decimal, side: OrderSide, slippage_bps: Decimal) -> Decimal:
    """Buys fill slightly above market and sells slightly below."""
    adjustment = market_price * slippage_bps / BPS
    price = market_price + adjustment if side is OrderSide.BUY else market_price - adjustment
    return price.quantize(PRICE_PLACES, rounding=ROUND_HALF_UP)


def apply_fill(
    quantity: Decimal,
    average_cost: Decimal,
    side: OrderSide,
    fill_qty: Decimal,
    fill_price: Decimal,
) -> tuple[Decimal, Decimal]:
    """New (quantity, average_cost) for a position after a fill."""
    if side is OrderSide.BUY:
        new_qty = quantity + fill_qty
        new_avg = (quantity * average_cost + fill_qty * fill_price) / new_qty
        return new_qty, new_avg.quantize(PRICE_PLACES, rounding=ROUND_HALF_UP)
    new_qty = quantity - fill_qty
    # Selling doesn't change the cost basis of the shares that remain.
    return new_qty, average_cost if new_qty > 0 else Decimal("0")


def replay_positions(executions: Iterable[Execution]) -> dict[str, tuple[Decimal, Decimal]]:
    """Rebuild positions from fills alone. Must always match the positions table."""
    positions: dict[str, tuple[Decimal, Decimal]] = {}
    for e in executions:
        qty, avg = positions.get(e.symbol, (Decimal("0"), Decimal("0")))
        positions[e.symbol] = apply_fill(qty, avg, e.side, e.quantity, e.price)
    return {symbol: p for symbol, p in positions.items() if p[0] > 0}


class TradingService:
    def __init__(
        self,
        session: Session,
        market: MarketDataService,
        settings: ExecutionSettings | None = None,
        risk_engine: RiskEngine | None = None,
    ):
        self.session = session
        self.market = market
        self.settings = settings or ExecutionSettings()
        self.risk_engine = risk_engine or RiskEngine()
        self.portfolios = PortfolioService(session)

    def submit_order(
        self,
        portfolio_id: uuid.UUID,
        symbol: str,
        side: OrderSide,
        quantity: Decimal,
        client_order_id: str | None = None,
        source: str = "manual",
    ) -> SubmitResult:
        client_order_id = client_order_id or str(uuid.uuid4())
        self.portfolios.get_portfolio(portfolio_id)
        if existing := self._find_order(portfolio_id, client_order_id):
            return SubmitResult(existing, created=False)

        # 1. External data first: fetching prices may commit the price cache.
        held = [p.symbol for p in self.portfolios.get_positions(portfolio_id)]
        latest, price_error = self._latest_prices([symbol, *held])
        market_open = self._market_open()

        # 2. Lock the portfolio; everything below is one transaction.
        portfolio = self.session.scalar(
            select(Portfolio).where(Portfolio.id == portfolio_id).with_for_update()
        )
        if portfolio is None:
            raise PortfolioNotFoundError(portfolio_id)
        self.session.expire_all()  # re-read state that may have changed before we held the lock
        if existing := self._find_order(portfolio_id, client_order_id):
            self.session.rollback()
            return SubmitResult(existing, created=False)

        price, price_problem = self._usable_price(symbol, latest, price_error)
        fill_price = (
            simulated_fill_price(price, side, self.settings.slippage_bps)
            if price is not None
            else None
        )
        positions = self.portfolios.get_positions(portfolio_id)
        market_prices = {p.symbol: p.price for p in latest.prices} if latest else {}
        ctx = RiskContext(
            portfolio_status=portfolio.status,
            max_position_pct=portfolio.max_position_pct,
            min_cash_pct=portfolio.min_cash_pct,
            cash=self.portfolios.get_cash_balance(portfolio_id),
            holdings={p.symbol: p.quantity for p in positions},
            valuation_prices={
                p.symbol: market_prices.get(p.symbol, p.average_cost) for p in positions
            },
            price=price,
            price_problem=price_problem,
            fill_price=fill_price,
            commission=self.settings.commission_per_order,
            market_open=market_open,
            enforce_market_hours=self.settings.enforce_market_hours,
        )

        # 3. Record the order and every check result.
        order = Order(
            portfolio_id=portfolio_id,
            client_order_id=client_order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            status=OrderStatus.PENDING,
            source=source,
            reference_price=price,
        )
        self.session.add(order)
        results = self.risk_engine.evaluate(ProposedOrder(symbol, side, quantity), ctx)
        for sequence, result in enumerate(results):
            order.risk_checks.append(
                RiskCheckResult(
                    sequence=sequence,
                    check_name=result.name,
                    passed=result.passed,
                    message=result.message,
                )
            )

        failures = [r.message for r in results if not r.passed]
        if failures:
            order.status = OrderStatus.REJECTED
            order.rejection_reason = "; ".join(failures)
        else:
            order.status = OrderStatus.APPROVED
            # 4. Execute in the same transaction.
            self._execute(order, price, fill_price)
        self.session.commit()
        # Reload from the database so responses match what was stored (e.g. numeric scale).
        self.session.expire(order)
        if order.execution is not None:
            self.session.expire(order.execution)
        return SubmitResult(order, created=True)

    def list_orders(self, portfolio_id: uuid.UUID) -> list[Order]:
        self.portfolios.get_portfolio(portfolio_id)
        return list(
            self.session.scalars(
                select(Order)
                .where(Order.portfolio_id == portfolio_id)
                .order_by(Order.created_at.desc())
            )
        )

    def get_order(self, portfolio_id: uuid.UUID, order_id: uuid.UUID) -> Order | None:
        self.portfolios.get_portfolio(portfolio_id)
        return self.session.scalar(
            select(Order).where(Order.portfolio_id == portfolio_id, Order.id == order_id)
        )

    def list_executions(self, portfolio_id: uuid.UUID) -> list[Execution]:
        self.portfolios.get_portfolio(portfolio_id)
        return list(
            self.session.scalars(
                select(Execution)
                .where(Execution.portfolio_id == portfolio_id)
                .order_by(Execution.executed_at, Execution.id)
            )
        )

    def _execute(self, order: Order, market_price: Decimal, fill_price: Decimal) -> None:
        commission = self.settings.commission_per_order
        execution = Execution(
            portfolio_id=order.portfolio_id,
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=fill_price,
            market_price=market_price,
            gross_amount=gross_amount(order.quantity, fill_price),
            commission=commission,
        )
        order.execution = execution
        self.session.flush()

        signed = -execution.gross_amount if order.side is OrderSide.BUY else execution.gross_amount
        self.session.add(
            CashLedgerEntry(
                portfolio_id=order.portfolio_id,
                entry_type=LedgerEntryType(order.side.value),
                amount=signed,
                description=(
                    f"{order.side} {order.quantity.normalize():f} {order.symbol}"
                    f" @ ${fill_price:,.4f}"
                ),
                reference_id=str(execution.id),
                idempotency_key=f"execution:{execution.id}",
            )
        )
        if commission > 0:
            self.session.add(
                CashLedgerEntry(
                    portfolio_id=order.portfolio_id,
                    entry_type=LedgerEntryType.FEE,
                    amount=-commission,
                    description=f"Commission for {order.side} {order.symbol}",
                    reference_id=str(execution.id),
                    idempotency_key=f"commission:{execution.id}",
                )
            )

        position = self.session.scalar(
            select(Position).where(
                Position.portfolio_id == order.portfolio_id, Position.symbol == order.symbol
            )
        )
        if position is None:
            position = Position(
                portfolio_id=order.portfolio_id,
                symbol=order.symbol,
                quantity=Decimal("0"),
                average_cost=Decimal("0"),
            )
            self.session.add(position)
        position.quantity, position.average_cost = apply_fill(
            position.quantity, position.average_cost, order.side, order.quantity, fill_price
        )
        order.status = OrderStatus.FILLED

    def _find_order(self, portfolio_id: uuid.UUID, client_order_id: str) -> Order | None:
        return self.session.scalar(
            select(Order).where(
                Order.portfolio_id == portfolio_id, Order.client_order_id == client_order_id
            )
        )

    def _latest_prices(self, symbols: list[str]) -> tuple[LatestPrices | None, str | None]:
        try:
            return self.market.get_latest_prices(symbols), None
        except MarketDataUnavailableError as exc:
            return None, str(exc)

    def _market_open(self) -> bool | None:
        if not self.settings.enforce_market_hours:
            return None
        try:
            return self.market.get_market_clock().is_open
        except MarketDataUnavailableError:
            return None

    def _usable_price(
        self, symbol: str, latest: LatestPrices | None, price_error: str | None
    ) -> tuple[Decimal | None, str | None]:
        """The order symbol's price, or why it can't be traded on."""
        if latest is None:
            return None, f"Market data unavailable: {price_error}"
        snapshot = next((p for p in latest.prices if p.symbol == symbol), None)
        if snapshot is None:
            return None, f"No market price for {symbol}"
        if snapshot.stale:
            return None, f"{symbol} price is stale ({latest.provider_error})"
        age = self.market.now() - snapshot.fetched_at
        if age > self.settings.max_price_age:
            return None, f"{symbol} price is {int(age.total_seconds())}s old"
        return snapshot.price, None
