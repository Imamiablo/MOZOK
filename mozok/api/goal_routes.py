from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from mozok.db.session import get_db
from mozok.goals.service import GoalService, format_goal_for_prompt_line, reads_from_records
from mozok.schemas.goals import AgentGoalContextResponse, AgentGoalPatch, AgentGoalRead, AgentGoalUpsert


router = APIRouter(tags=["goals"])


@router.post("/goals/upsert", response_model=AgentGoalRead)
def upsert_goal(data: AgentGoalUpsert, db: Session = Depends(get_db)):
    record = GoalService(db).upsert(data)
    return AgentGoalRead.from_record(record)


@router.patch("/goals/{goal_id}", response_model=AgentGoalRead)
def patch_goal(goal_id: int, data: AgentGoalPatch, db: Session = Depends(get_db)):
    record = GoalService(db).patch(goal_id, data)
    if record is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    return AgentGoalRead.from_record(record)


@router.delete("/goals/{goal_id}")
def delete_goal(goal_id: int, db: Session = Depends(get_db)):
    ok = GoalService(db).soft_delete(goal_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Goal not found")
    return {"deleted": True, "goal_id": goal_id}


@router.get("/agents/{agent_id}/goals", response_model=list[AgentGoalRead])
def list_agent_goals(
    agent_id: str,
    status: str | None = Query(default=None, description="Optional status filter, e.g. active, blocked, completed."),
    include_inactive: bool = Query(default=False),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    records = GoalService(db).list_goals(
        agent_id=agent_id,
        status=status,
        include_inactive=include_inactive,
        limit=limit,
    )
    return reads_from_records(records)


@router.get("/agents/{agent_id}/goals/context", response_model=AgentGoalContextResponse)
def get_agent_goals_context(
    agent_id: str,
    status: str | None = Query(default=None, description="Optional status filter, e.g. active, blocked, completed."),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    records = GoalService(db).list_goals(
        agent_id=agent_id,
        status=status,
        include_inactive=False,
        limit=limit,
    )
    goals = reads_from_records(records)
    lines = [format_goal_for_prompt_line(goal) for goal in goals]
    return AgentGoalContextResponse(
        agent_id=agent_id,
        status=status,
        count=len(goals),
        lines=lines,
        goals=goals,
    )
