from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from mozok.db.session import get_db
from mozok.procedural_skills.service import (
    ProceduralSkillService,
    format_procedural_skill_for_prompt_line,
    reads_from_records,
)
from mozok.schemas.procedural_skills import (
    AgentProceduralSkillPatch,
    AgentProceduralSkillRead,
    AgentProceduralSkillUpsert,
    ProceduralSkillContextResponse,
    ProceduralSkillSelectionResponse,
)


router = APIRouter(tags=["procedural-skills"])


@router.post("/procedural-skills/upsert", response_model=AgentProceduralSkillRead)
def upsert_procedural_skill(data: AgentProceduralSkillUpsert, db: Session = Depends(get_db)):
    record = ProceduralSkillService(db).upsert(data)
    return AgentProceduralSkillRead.from_record(record)


@router.patch("/procedural-skills/{skill_id}", response_model=AgentProceduralSkillRead)
def patch_procedural_skill(skill_id: int, data: AgentProceduralSkillPatch, db: Session = Depends(get_db)):
    record = ProceduralSkillService(db).patch(skill_id, data)
    if record is None:
        raise HTTPException(status_code=404, detail="Procedural skill not found")
    return AgentProceduralSkillRead.from_record(record)


@router.delete("/procedural-skills/{skill_id}")
def delete_procedural_skill(skill_id: int, db: Session = Depends(get_db)):
    ok = ProceduralSkillService(db).soft_delete(skill_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Procedural skill not found")
    return {"deleted": True, "skill_id": skill_id}


@router.get("/agents/{agent_id}/procedural-skills", response_model=list[AgentProceduralSkillRead])
def list_procedural_skills(
    agent_id: str,
    skill_type: str | None = None,
    status: str | None = Query(default="active"),
    include_inactive: bool = False,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    records = ProceduralSkillService(db).list_skills(
        agent_id=agent_id,
        skill_type=skill_type,
        status=status,
        include_inactive=include_inactive,
        limit=limit,
    )
    return reads_from_records(records)


@router.get("/agents/{agent_id}/procedural-skills/context", response_model=ProceduralSkillContextResponse)
def procedural_skill_context(
    agent_id: str,
    skill_type: str | None = None,
    status: str | None = Query(default="active"),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    records = ProceduralSkillService(db).list_skills(
        agent_id=agent_id,
        skill_type=skill_type,
        status=status,
        include_inactive=False,
        limit=limit,
    )
    skills = reads_from_records(records)
    return ProceduralSkillContextResponse(
        agent_id=agent_id,
        count=len(skills),
        lines=[format_procedural_skill_for_prompt_line(skill) for skill in skills],
        skills=skills,
    )


@router.get("/agents/{agent_id}/procedural-skills/select", response_model=ProceduralSkillSelectionResponse)
def select_procedural_skills(
    agent_id: str,
    message: str = Query(default="", description="Current user message or scene text used for trigger keyword matching."),
    skill_type: str | None = None,
    status: str | None = Query(default="active"),
    goal_keys: list[str] = Query(default=[]),
    lorebook_keys: list[str] = Query(default=[]),
    entity_ids: list[str] = Query(default=[]),
    min_score: float = Query(default=1.0, ge=0.0, le=100.0),
    fallback_to_priority: bool = True,
    limit: int = Query(default=5, ge=0, le=50),
    db: Session = Depends(get_db),
):
    records, selection = ProceduralSkillService(db).select_relevant_skills(
        agent_id=agent_id,
        user_message=message,
        skill_type=skill_type,
        status=status,
        goal_keys=goal_keys,
        lorebook_keys=lorebook_keys,
        entity_ids=entity_ids,
        limit=limit,
        min_score=min_score,
        fallback_to_priority=fallback_to_priority,
    )
    skills = reads_from_records(records)
    return ProceduralSkillSelectionResponse(
        agent_id=agent_id,
        count=len(skills),
        selection=selection,
        lines=[format_procedural_skill_for_prompt_line(skill) for skill in skills],
        skills=skills,
    )
