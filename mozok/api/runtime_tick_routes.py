from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from mozok.db.session import get_db
from mozok.runtime_tick.schemas import AgentRuntimeTickRequest, AgentRuntimeTickResponse
from mozok.runtime_tick.service import AgentRuntimeTickService

router = APIRouter(tags=["agent runtime tick"])


@router.post("/agents/{agent_id}/tick", response_model=AgentRuntimeTickResponse)
def run_agent_runtime_tick(agent_id: str, data: AgentRuntimeTickRequest, db: Session = Depends(get_db)) -> AgentRuntimeTickResponse:
    return AgentRuntimeTickService(db).tick(agent_id, data)
