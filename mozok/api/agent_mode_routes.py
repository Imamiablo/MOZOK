from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from mozok.agent.service import AgentService
from mozok.agent_modes.profiles import BUILTIN_AGENT_MODE_PROFILES
from mozok.agent_modes.schemas import AgentModeProfile, AgentModeResolveRequest, AgentModeResolveResponse
from mozok.agent_modes.service import AgentModeService
from mozok.db.session import get_db

router = APIRouter(tags=["agent-modes"])


@router.get("/agent-modes", response_model=list[AgentModeProfile])
def list_agent_modes():
    return AgentModeService().list_profiles()


@router.get("/agent-modes/{mode}", response_model=AgentModeProfile)
def get_agent_mode(mode: str):
    profile = BUILTIN_AGENT_MODE_PROFILES.get(mode)
    if profile is None:
        raise HTTPException(status_code=404, detail="Agent mode not found")
    return profile


@router.post("/agents/{agent_id}/agent-mode/resolve", response_model=AgentModeResolveResponse)
def resolve_agent_mode(agent_id: str, data: AgentModeResolveRequest | None = None, db: Session = Depends(get_db)):
    agent = AgentService(db).get_or_create_default_agent(agent_id)
    request = data or AgentModeResolveRequest()
    return AgentModeService().resolve(agent, agent_mode=request.agent_mode, overrides=request.overrides)
