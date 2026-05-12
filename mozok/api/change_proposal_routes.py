from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from mozok.change_proposals.schemas import (
    ChangeProposalAutoPolicyRequest,
    ChangeProposalAutoPolicyResponse,
    ChangeProposalCreate,
    ChangeProposalDecisionRequest,
    ChangeProposalDecisionResponse,
    ChangeProposalListResponse,
    ChangeProposalRead,
)
from mozok.change_proposals.service import ChangeProposalService
from mozok.core.bot_core import get_memory_service
from mozok.db.session import get_db

router = APIRouter(tags=["change proposals"])


@router.post("/agents/{agent_id}/change-proposals", response_model=ChangeProposalRead)
def create_change_proposal(agent_id: str, data: ChangeProposalCreate, db: Session = Depends(get_db)):
    return ChangeProposalService(db=db, memory_service=get_memory_service(db)).create(agent_id, data)


@router.get("/agents/{agent_id}/change-proposals", response_model=ChangeProposalListResponse)
def list_change_proposals(
    agent_id: str,
    status: str | None = None,
    proposal_type: str | None = None,
    db: Session = Depends(get_db),
):
    return ChangeProposalService(db=db, memory_service=get_memory_service(db)).list(
        agent_id=agent_id,
        status=status,
        proposal_type=proposal_type,
    )


@router.post("/agents/{agent_id}/change-proposals/apply", response_model=ChangeProposalDecisionResponse)
def apply_change_proposals(agent_id: str, data: ChangeProposalDecisionRequest, db: Session = Depends(get_db)):
    return ChangeProposalService(db=db, memory_service=get_memory_service(db)).apply(agent_id, data)


@router.post("/agents/{agent_id}/change-proposals/reject", response_model=ChangeProposalDecisionResponse)
def reject_change_proposals(agent_id: str, data: ChangeProposalDecisionRequest, db: Session = Depends(get_db)):
    return ChangeProposalService(db=db, memory_service=get_memory_service(db)).reject(agent_id, data)


@router.post("/agents/{agent_id}/change-proposals/auto-apply", response_model=ChangeProposalAutoPolicyResponse)
def auto_apply_change_proposals(agent_id: str, data: ChangeProposalAutoPolicyRequest, db: Session = Depends(get_db)):
    return ChangeProposalService(db=db, memory_service=get_memory_service(db)).auto_apply(agent_id, data)
