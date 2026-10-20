from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.agent.service import UnknownStrategyError
from app.api import admin, agent, market, orders, portfolios
from app.api.auth import require_admin_for_writes
from app.llm.client import LLMUnavailableError
from app.market_data.provider import MarketDataUnavailableError
from app.services.portfolio import PortfolioClosedError, PortfolioNotFoundError

# Reads are public; every change requires the admin key (see app/api/auth.py).
app = FastAPI(title="AlphaLab", version="0.1.0", dependencies=[Depends(require_admin_for_writes)])

# On Vercel the API is served under /api and receives that prefix; the local Vite
# dev server strips it before proxying. Strip it here too so routes work in both.
API_PREFIX = "/api"


@app.middleware("http")
async def strip_api_prefix(request: Request, call_next):
    path = request.scope["path"]
    if path == API_PREFIX or path.startswith(API_PREFIX + "/"):
        request.scope["path"] = path.removeprefix(API_PREFIX) or "/"
    return await call_next(request)


app.include_router(portfolios.router)
app.include_router(orders.router)
app.include_router(agent.router)
app.include_router(market.router)
app.include_router(admin.router)


@app.exception_handler(PortfolioNotFoundError)
def portfolio_not_found(_: Request, exc: PortfolioNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(PortfolioClosedError)
def portfolio_closed(_: Request, exc: PortfolioClosedError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": f"{exc}; closed portfolios can't be paused or resumed."},
    )


@app.exception_handler(MarketDataUnavailableError)
def market_data_unavailable(_: Request, exc: MarketDataUnavailableError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)}
    )


@app.exception_handler(LLMUnavailableError)
def llm_unavailable(_: Request, exc: LLMUnavailableError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)}
    )


@app.exception_handler(UnknownStrategyError)
def unknown_strategy(_: Request, exc: UnknownStrategyError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": f"{exc}. Agent runs need a portfolio with strategy_id 'ai-trading-v1'."},
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
