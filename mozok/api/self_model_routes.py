from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from mozok.db.session import get_db
from mozok.self_model.schemas import SelfModelProposalRequest, SelfModelProposalResponse, SelfModelRequest, SelfModelResponse
from mozok.self_model.service import SelfModelService

router = APIRouter(tags=["self model"])


@router.post("/agents/{agent_id}/self-model/preview", response_model=SelfModelResponse)
def preview_self_model(agent_id: str, data: SelfModelRequest, db: Session = Depends(get_db)):
    return SelfModelService(db).preview(agent_id, data)


@router.post("/agents/{agent_id}/self-model/propose-update", response_model=SelfModelProposalResponse)
def propose_self_model_update(agent_id: str, data: SelfModelProposalRequest, db: Session = Depends(get_db)):
    return SelfModelService(db).propose_update(agent_id, data)
