from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from mozok.db.session import get_db
from mozok.runtime_tick.schemas import AgentRuntimeBatchTickRequest, AgentRuntimeBatchTickResponse, AgentRuntimeTickHistoryResponse, AgentRuntimeTickRequest, AgentRuntimeTickResponse
from mozok.runtime_tick.service import AgentRuntimeTickService

router = APIRouter(tags=["agent runtime tick"])


@router.post("/agents/{agent_id}/tick", response_model=AgentRuntimeTickResponse)
def run_agent_runtime_tick(agent_id: str, data: AgentRuntimeTickRequest, db: Session = Depends(get_db)) -> AgentRuntimeTickResponse:
    return AgentRuntimeTickService(db).tick(agent_id, data)


@router.post("/runtime/tick/batch", response_model=AgentRuntimeBatchTickResponse)
def run_agent_runtime_batch_tick(data: AgentRuntimeBatchTickRequest, db: Session = Depends(get_db)) -> AgentRuntimeBatchTickResponse:
    return AgentRuntimeTickService(db).batch_tick(data)


@router.get("/agents/{agent_id}/tick/history", response_model=AgentRuntimeTickHistoryResponse)
def get_agent_runtime_tick_history(agent_id: str, limit: int = 20, db: Session = Depends(get_db)) -> AgentRuntimeTickHistoryResponse:
    return AgentRuntimeTickService(db).history(agent_id, limit=limit)
