"""
FastAPI routes for Lorebook.

- /lorebook/... manages objective world facts.
- /agents/{agent_id}/lorebook/... manages what an agent knows.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from mozok.db.session import get_db
from mozok.lorebook.schemas import (
    AgentLorebookKnowledgeRead,
    AgentLorebookKnowledgeUpsert,
    LorebookContextResponse,
    LorebookEntryRead,
    LorebookEntryUpsert,
)
from mozok.lorebook.service import LorebookService, format_lorebook_context

router = APIRouter(tags=["lorebook"])


def _entry_to_read(entry) -> LorebookEntryRead:
    return LorebookEntryRead(
        id=entry.id,
        world_id=entry.world_id,
        entry_key=entry.entry_key,
        title=entry.title,
        content=entry.content,
        category=entry.category,
        visibility=entry.visibility,
        importance=entry.importance,
        tags=entry.tags or [],
        metadata=entry.entry_metadata or {},
        is_active=entry.is_active,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )


def _knowledge_to_read(link) -> AgentLorebookKnowledgeRead:
    return AgentLorebookKnowledgeRead(
        id=link.id,
        agent_id=link.agent_id,
        lorebook_entry_id=link.lorebook_entry_id,
        knowledge_state=link.knowledge_state,
        confidence=link.confidence,
        notes=link.notes,
        metadata=link.knowledge_metadata or {},
        is_active=link.is_active,
        entry=_entry_to_read(link.entry),
    )


@router.post("/lorebook/upsert", response_model=LorebookEntryRead)
def upsert_lorebook_entry(payload: LorebookEntryUpsert, db: Session = Depends(get_db)):
    service = LorebookService(db)
    entry = service.upsert_entry(payload)
    return _entry_to_read(entry)


@router.get("/lorebook", response_model=list[LorebookEntryRead])
def list_lorebook_entries(
    world_id: str = Query("default"),
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db),
):
    service = LorebookService(db)
    return [_entry_to_read(entry) for entry in service.list_entries(world_id, include_inactive)]


@router.post("/agents/{agent_id}/lorebook/knowledge", response_model=AgentLorebookKnowledgeRead)
def upsert_agent_lorebook_knowledge(
    agent_id: str,
    payload: AgentLorebookKnowledgeUpsert,
    db: Session = Depends(get_db),
):
    if payload.agent_id != agent_id:
        raise HTTPException(status_code=400, detail="Path agent_id must match payload.agent_id.")

    service = LorebookService(db)
    try:
        link = service.upsert_agent_knowledge(payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    db.refresh(link)
    return _knowledge_to_read(link)


@router.get("/agents/{agent_id}/lorebook/context", response_model=LorebookContextResponse)
def get_agent_lorebook_context(
    agent_id: str,
    world_id: str = Query("default"),
    limit: int = Query(10, ge=0, le=50),
    include_public: bool = Query(True),
    include_narrator_only: bool = Query(False),
    db: Session = Depends(get_db),
):
    service = LorebookService(db)
    items = service.build_agent_lorebook_context(
        agent_id=agent_id,
        world_id=world_id,
        limit=limit,
        include_public=include_public,
        include_narrator_only=include_narrator_only,
    )
    return LorebookContextResponse(
        agent_id=agent_id,
        world_id=world_id,
        include_public=include_public,
        include_narrator_only=include_narrator_only,
        count=len(items),
        items=items,
        context_text=format_lorebook_context(items),
    )
