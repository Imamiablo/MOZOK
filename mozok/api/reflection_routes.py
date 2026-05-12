from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from mozok.core.bot_core import get_memory_service
from mozok.db.session import get_db
from mozok.reflection.schemas import ReflectionRequest, ReflectionResponse
from mozok.reflection.service import ReflectionService

router = APIRouter(tags=["reflection"])


@router.post("/agents/{agent_id}/reflection/preview", response_model=ReflectionResponse)
def preview_reflection(agent_id: str, data: ReflectionRequest, db: Session = Depends(get_db)):
    data.agent_id = agent_id
    data.create_change_proposals = False
    return ReflectionService(db=db, memory_service=get_memory_service(db)).reflect(data)


@router.post("/agents/{agent_id}/reflection/run", response_model=ReflectionResponse)
def run_reflection(agent_id: str, data: ReflectionRequest, db: Session = Depends(get_db)):
    data.agent_id = agent_id
    return ReflectionService(db=db, memory_service=get_memory_service(db)).reflect(data)
