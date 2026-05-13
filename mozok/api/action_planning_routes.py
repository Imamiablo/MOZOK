from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from mozok.action_planning.schemas import ActionPlanRequest, ActionPlanResponse, ActionProposalRequest, ActionProposalResponse
from mozok.action_planning.service import ActionPlanningService
from mozok.db.session import get_db

router = APIRouter(tags=["action planning"])


@router.post("/agents/{agent_id}/actions/plan", response_model=ActionPlanResponse)
def plan_agent_action(agent_id: str, data: ActionPlanRequest, db: Session = Depends(get_db)):
    return ActionPlanningService(db).plan(agent_id, data)


@router.post("/agents/{agent_id}/actions/propose", response_model=ActionProposalResponse)
def propose_agent_action(agent_id: str, data: ActionProposalRequest, db: Session = Depends(get_db)):
    return ActionPlanningService(db).propose(agent_id, data)
