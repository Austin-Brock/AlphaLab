import uuid

from fastapi import APIRouter, HTTPException, status

from app.api.deps import AgentRunServiceDep
from app.schemas import AgentRunCreate, AgentRunOut, AgentRunSummaryOut

router = APIRouter(prefix="/portfolios/{portfolio_id}/agent-runs", tags=["ai agent"])


@router.post("", response_model=AgentRunOut, status_code=status.HTTP_201_CREATED)
def start_run(
    portfolio_id: uuid.UUID, agent: AgentRunServiceDep, body: AgentRunCreate | None = None
):
    """Run the portfolio's strategy now. Blocks until the model finishes (usually < 1 minute)."""
    return agent.run(portfolio_id, run_key=body.run_key if body else None)


@router.get("", response_model=list[AgentRunSummaryOut])
def list_runs(portfolio_id: uuid.UUID, agent: AgentRunServiceDep):
    return agent.list_runs(portfolio_id)


@router.get("/{run_id}", response_model=AgentRunOut)
def get_run(portfolio_id: uuid.UUID, run_id: uuid.UUID, agent: AgentRunServiceDep):
    run = agent.get_run(portfolio_id, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Agent run {run_id} not found")
    return run
