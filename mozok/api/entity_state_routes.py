from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from mozok.db.session import get_db
from mozok.entity_state.service import EntityStateService, reads_from_records
from mozok.schemas.entity_state import (
    EntityStateContextResponse,
    EntityStatePatch,
    EntityStateRead,
    EntityStateUpsert,
)


router = APIRouter(tags=["entity-states"])


def get_entity_state_service(db: Session = Depends(get_db)) -> EntityStateService:
    return EntityStateService(db)


@router.post("/entity-states/upsert", response_model=EntityStateRead)
def upsert_entity_state(
    data: EntityStateUpsert,
    service: EntityStateService = Depends(get_entity_state_service),
):
    """Create or update structured state for one agent/entity/state_kind triple."""

    return EntityStateRead.from_record(service.upsert(data))


@router.patch("/entity-states/{state_id}", response_model=EntityStateRead)
def patch_entity_state(
    state_id: int,
    data: EntityStatePatch,
    service: EntityStateService = Depends(get_entity_state_service),
):
    record = service.patch(state_id, data)
    if record is None:
        raise HTTPException(status_code=404, detail="Entity state not found")
    return EntityStateRead.from_record(record)


@router.delete("/entity-states/{state_id}")
def delete_entity_state(
    state_id: int,
    service: EntityStateService = Depends(get_entity_state_service),
):
    ok = service.soft_delete(state_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Entity state not found")
    return {"deleted": True, "state_id": state_id}


@router.get("/agents/{agent_id}/entity-states", response_model=list[EntityStateRead])
def list_agent_entity_states(
    agent_id: str,
    state_kind: str | None = None,
    entity_id: str | None = None,
    include_inactive: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    service: EntityStateService = Depends(get_entity_state_service),
):
    records = service.list_states(
        agent_id=agent_id,
        state_kind=state_kind,
        entity_id=entity_id,
        include_inactive=include_inactive,
        limit=limit,
    )
    return reads_from_records(records)


@router.get("/agents/{agent_id}/entity-states/context", response_model=EntityStateContextResponse)
def get_agent_entity_state_context(
    agent_id: str,
    state_kind: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(default=10, ge=1, le=50),
    service: EntityStateService = Depends(get_entity_state_service),
):
    records = service.list_states(
        agent_id=agent_id,
        state_kind=state_kind,
        entity_id=entity_id,
        include_inactive=False,
        limit=limit,
    )
    states = reads_from_records(records)
    lines = [service_line for service_line in service.format_context_lines(agent_id, state_kind, entity_id, limit)]
    return EntityStateContextResponse(agent_id=agent_id, count=len(states), lines=lines, states=states)
