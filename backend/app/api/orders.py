import uuid
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Response, status

from app.api.deps import TradingServiceDep
from app.schemas import ExecutionOut, OrderCreate, OrderOut

router = APIRouter(prefix="/portfolios/{portfolio_id}", tags=["trading"])


@router.post(
    "/orders",
    response_model=OrderOut,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"description": "Order with this client_order_id already exists"}},
)
def submit_order(
    portfolio_id: uuid.UUID, body: OrderCreate, trading: TradingServiceDep, response: Response
):
    """Submit a manual order. Rejected orders are still recorded and returned (with reasons)."""
    result = trading.submit_order(
        portfolio_id,
        symbol=body.symbol.upper(),
        side=body.side,
        quantity=Decimal(body.quantity),
        client_order_id=body.client_order_id,
        source="manual",
    )
    if not result.created:
        response.status_code = status.HTTP_200_OK
    return result.order


@router.get("/orders", response_model=list[OrderOut])
def list_orders(portfolio_id: uuid.UUID, trading: TradingServiceDep):
    return trading.list_orders(portfolio_id)


@router.get("/orders/{order_id}", response_model=OrderOut)
def get_order(portfolio_id: uuid.UUID, order_id: uuid.UUID, trading: TradingServiceDep):
    order = trading.get_order(portfolio_id, order_id)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Order {order_id} not found")
    return order


@router.get("/executions", response_model=list[ExecutionOut])
def list_executions(portfolio_id: uuid.UUID, trading: TradingServiceDep):
    return trading.list_executions(portfolio_id)
