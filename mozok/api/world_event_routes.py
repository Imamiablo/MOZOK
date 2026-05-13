from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from mozok.db.session import get_db
from mozok.world_events.schemas import (
    WorldEventAcknowledgeRequest,
    WorldEventAcknowledgeResponse,
    WorldEventConsumeRequest,
    WorldEventConsumeResponse,
    WorldEventCreateRequest,
    WorldEventCreateResponse,
    WorldEventExpireRequest,
    WorldEventExpireResponse,
    WorldEventSearchRequest,
    WorldEventSearchResponse,
    WorldEventToPerceptionRequest,
    WorldEventToPerceptionResponse,
)
from mozok.world_events.service import WorldEventService

router = APIRouter(tags=["world event bus"])


@router.post("/world-events", response_model=WorldEventCreateResponse)
def create_world_events(data: WorldEventCreateRequest, db: Session = Depends(get_db)) -> WorldEventCreateResponse:
    return WorldEventService(db).create(data)


@router.post("/world-events/search", response_model=WorldEventSearchResponse)
def search_world_events(data: WorldEventSearchRequest, db: Session = Depends(get_db)) -> WorldEventSearchResponse:
    return WorldEventService(db).search(data)


@router.post("/world-events/consume", response_model=WorldEventConsumeResponse)
def consume_world_events(data: WorldEventConsumeRequest, db: Session = Depends(get_db)) -> WorldEventConsumeResponse:
    return WorldEventService(db).consume(data)


@router.post("/world-events/ack", response_model=WorldEventAcknowledgeResponse)
def acknowledge_world_events(data: WorldEventAcknowledgeRequest, db: Session = Depends(get_db)) -> WorldEventAcknowledgeResponse:
    return WorldEventService(db).acknowledge(data)


@router.post("/world-events/expire", response_model=WorldEventExpireResponse)
def expire_world_events(data: WorldEventExpireRequest, db: Session = Depends(get_db)) -> WorldEventExpireResponse:
    return WorldEventService(db).expire(data)


@router.post("/world-events/to-perception", response_model=WorldEventToPerceptionResponse)
def world_events_to_perception(data: WorldEventToPerceptionRequest, db: Session = Depends(get_db)) -> WorldEventToPerceptionResponse:
    return WorldEventService(db).to_perception_events(data)
