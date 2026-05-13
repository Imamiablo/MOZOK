from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from mozok.action_execution.schemas import (
    ActionExecutionListResponse,
    ActionExecutionRequest,
    ActionExecutionResponse,
    ActionExecutionResultUpdateRequest,
    ActionToolRegistryResponse,
    ActionToolRegistryUpdateRequest,
)
from mozok.action_execution.service import ActionExecutionService
from mozok.db.session import get_db

router = APIRouter(tags=["action execution"])


@router.get("/agents/{agent_id}/action-tools", response_model=ActionToolRegistryResponse)
def list_action_tools(agent_id: str, db: Session = Depends(get_db)) -> ActionToolRegistryResponse:
    return ActionExecutionService(db).registry(agent_id)


@router.post("/agents/{agent_id}/action-tools", response_model=ActionToolRegistryResponse)
def update_action_tools(agent_id: str, data: ActionToolRegistryUpdateRequest, db: Session = Depends(get_db)) -> ActionToolRegistryResponse:
    return ActionExecutionService(db).update_registry(agent_id, data)


@router.post("/agents/{agent_id}/actions/execute", response_model=ActionExecutionResponse)
def execute_action(agent_id: str, data: ActionExecutionRequest, db: Session = Depends(get_db)) -> ActionExecutionResponse:
    return ActionExecutionService(db).execute(agent_id, data)


@router.get("/agents/{agent_id}/actions/executions", response_model=ActionExecutionListResponse)
def list_action_executions(agent_id: str, limit: int = 50, db: Session = Depends(get_db)) -> ActionExecutionListResponse:
    return ActionExecutionService(db).list_executions(agent_id, limit=limit)


@router.post("/agents/{agent_id}/actions/executions/{execution_id}/result", response_model=ActionExecutionResponse)
def update_action_execution_result(
    agent_id: str,
    execution_id: str,
    data: ActionExecutionResultUpdateRequest,
    db: Session = Depends(get_db),
) -> ActionExecutionResponse:
    result = ActionExecutionService(db).update_result(agent_id, execution_id, data)
    if result is None:
        raise HTTPException(status_code=404, detail="Action execution not found")
    return result
