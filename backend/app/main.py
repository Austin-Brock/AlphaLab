from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api import market, portfolios
from app.market_data.provider import MarketDataUnavailableError
from app.services.portfolio import PortfolioNotFoundError

app = FastAPI(title="AlphaLab", version="0.1.0")
app.include_router(portfolios.router)
app.include_router(market.router)


@app.exception_handler(PortfolioNotFoundError)
def portfolio_not_found(_: Request, exc: PortfolioNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.exception_handler(MarketDataUnavailableError)
def market_data_unavailable(_: Request, exc: MarketDataUnavailableError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)}
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
