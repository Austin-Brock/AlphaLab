from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api import portfolios
from app.services.portfolio import PortfolioNotFoundError

app = FastAPI(title="AlphaLab", version="0.1.0")
app.include_router(portfolios.router)


@app.exception_handler(PortfolioNotFoundError)
def portfolio_not_found(_: Request, exc: PortfolioNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=status.HTTP_404_NOT_FOUND, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
