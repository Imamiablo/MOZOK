from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from mozok.db.session import get_db
from mozok.procedural_skills.service import (
    SHARED_SKILL_AGENT_ID,
    ProceduralSkillService,
    format_procedural_skill_for_prompt_line,
    reads_from_records,
)
from mozok.schemas.procedural_skills import (
    AgentProceduralSkillPatch,
    AgentProceduralSkillRead,
    AgentProceduralSkillUpsert,
    ProceduralSkillContextResponse,
    ProceduralSkillEffectivenessStats,
    ProceduralSkillFromTemplateRequest,
    ProceduralSkillRelationSuggestionsResponse,
    ProceduralSkillRelationSyncRequest,
    ProceduralSkillRelationSyncResponse,
    ProceduralSkillSelectionResponse,
    ProceduralSkillTemplateRead,
    ProceduralSkillUsageCreate,
    ProceduralSkillUsageRead,
    ProceduralSkillUsageResponse,
)


router = APIRouter(tags=["procedural-skills"])


@router.post("/procedural-skills/upsert", response_model=AgentProceduralSkillRead)
def upsert_procedural_skill(data: AgentProceduralSkillUpsert, db: Session = Depends(get_db)):
    record = ProceduralSkillService(db).upsert(data)
    return AgentProceduralSkillRead.from_record(record)


@router.post("/procedural-skills/shared/upsert", response_model=AgentProceduralSkillRead)
def upsert_shared_procedural_skill(data: AgentProceduralSkillUpsert, db: Session = Depends(get_db)):
    payload = data.model_copy(update={"agent_id": SHARED_SKILL_AGENT_ID})
    record = ProceduralSkillService(db).upsert(payload)
    return AgentProceduralSkillRead.from_record(record)


@router.get("/procedural-skills/shared", response_model=list[AgentProceduralSkillRead])
def list_shared_procedural_skills(
    skill_type: str | None = None,
    status: str | None = Query(default="active"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    records = ProceduralSkillService(db).list_skills(
        agent_id=SHARED_SKILL_AGENT_ID,
        skill_type=skill_type,
        status=status,
        include_inactive=False,
        limit=limit,
    )
    return reads_from_records(records)


@router.get("/procedural-skills/templates", response_model=list[ProceduralSkillTemplateRead])
def list_procedural_skill_templates(db: Session = Depends(get_db)):
    return ProceduralSkillService(db).list_builtin_templates()


@router.post("/agents/{agent_id}/procedural-skills/from-template", response_model=AgentProceduralSkillRead)
def create_procedural_skill_from_template(
    agent_id: str,
    data: ProceduralSkillFromTemplateRequest,
    db: Session = Depends(get_db),
):
    record = ProceduralSkillService(db).create_from_template(agent_id=agent_id, request=data)
    if record is None:
        raise HTTPException(status_code=404, detail="Procedural skill template not found")
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
    include_shared: bool = Query(default=False, description="Also include shared library skills under __shared__."),
    include_effectiveness: bool = Query(default=False, description="Attach usage/effectiveness stats for each returned skill."),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    service = ProceduralSkillService(db)
    records = service.list_skills(
        agent_id=agent_id,
        skill_type=skill_type,
        status=status,
        include_inactive=include_inactive,
        include_shared=include_shared,
        limit=limit,
    )
    if not include_effectiveness:
        return reads_from_records(records)
    return [
        AgentProceduralSkillRead.from_record(record, effectiveness=service.effectiveness_stats(int(record.id)))
        for record in records
    ]


@router.get("/agents/{agent_id}/procedural-skills/context", response_model=ProceduralSkillContextResponse)
def procedural_skill_context(
    agent_id: str,
    skill_type: str | None = None,
    status: str | None = Query(default="active"),
    include_shared: bool = Query(default=False),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    records = ProceduralSkillService(db).list_skills(
        agent_id=agent_id,
        skill_type=skill_type,
        status=status,
        include_inactive=False,
        include_shared=include_shared,
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
    include_shared: bool = Query(default=False),
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
        include_shared=include_shared,
    )
    skills = reads_from_records(records)
    return ProceduralSkillSelectionResponse(
        agent_id=agent_id,
        count=len(skills),
        selection=selection,
        lines=[format_procedural_skill_for_prompt_line(skill) for skill in skills],
        skills=skills,
    )


@router.post("/procedural-skills/{skill_id}/usage-results", response_model=ProceduralSkillUsageResponse)
def record_procedural_skill_usage_result(
    skill_id: int,
    data: ProceduralSkillUsageCreate,
    db: Session = Depends(get_db),
):
    response = ProceduralSkillService(db).record_usage_result(skill_id=skill_id, data=data)
    if response is None:
        raise HTTPException(status_code=404, detail="Procedural skill not found")
    return response


@router.get("/procedural-skills/{skill_id}/usage-results", response_model=list[ProceduralSkillUsageRead])
def list_procedural_skill_usage_results(
    skill_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    response = ProceduralSkillService(db).list_usage_results(skill_id=skill_id, limit=limit)
    if response is None:
        raise HTTPException(status_code=404, detail="Procedural skill not found")
    return response


@router.get("/procedural-skills/{skill_id}/effectiveness", response_model=ProceduralSkillEffectivenessStats)
def get_procedural_skill_effectiveness(skill_id: int, db: Session = Depends(get_db)):
    stats = ProceduralSkillService(db).effectiveness_stats(skill_id=skill_id)
    if stats is None:
        raise HTTPException(status_code=404, detail="Procedural skill not found")
    return stats


@router.get("/procedural-skills/{skill_id}/relation-suggestions", response_model=ProceduralSkillRelationSuggestionsResponse)
def get_procedural_skill_relation_suggestions(
    skill_id: int,
    world_id: str = Query(default="default"),
    db: Session = Depends(get_db),
):
    response = ProceduralSkillService(db).relation_suggestions(skill_id=skill_id, world_id=world_id)
    if response is None:
        raise HTTPException(status_code=404, detail="Procedural skill not found")
    return response


@router.post("/procedural-skills/{skill_id}/relations/sync", response_model=ProceduralSkillRelationSyncResponse)
def sync_procedural_skill_relations(
    skill_id: int,
    data: ProceduralSkillRelationSyncRequest,
    db: Session = Depends(get_db),
):
    response = ProceduralSkillService(db).sync_skill_relations(skill_id=skill_id, request=data)
    if response is None:
        raise HTTPException(status_code=404, detail="Procedural skill not found")
    return response
