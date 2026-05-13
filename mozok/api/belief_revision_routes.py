from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from mozok.belief_revision.schemas import BeliefRevisionRequest, BeliefRevisionResponse
from mozok.belief_revision.service import BeliefRevisionService
from mozok.db.session import get_db

router = APIRouter(tags=["belief revision"])


@router.post("/agents/{agent_id}/belief-revision/preview", response_model=BeliefRevisionResponse)
def preview_belief_revision(agent_id: str, data: BeliefRevisionRequest, db: Session = Depends(get_db)):
    data.create_change_proposal = False
    return BeliefRevisionService(db).preview(agent_id, data)


@router.post("/agents/{agent_id}/belief-revision/propose", response_model=BeliefRevisionResponse)
def propose_belief_revision(agent_id: str, data: BeliefRevisionRequest, db: Session = Depends(get_db)):
    data.create_change_proposal = True
    return BeliefRevisionService(db).preview(agent_id, data)
