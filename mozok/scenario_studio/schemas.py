from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ScenarioStudioAgentDraft(BaseModel):
    agent_id: str = Field(..., examples=["npc_alice_showcase"])
    name: str = "Unnamed Agent"
    role: str = Field(default="character", examples=["npc", "narrator", "assistant", "world_director"])
    description: str = ""
    personality: str = ""
    system_prompt: str = "Use only provided context and stay consistent."
    mode: str | None = Field(default=None, examples=["roleplay_character", "narrator", "assistant"])


class ScenarioStudioLoreDraft(BaseModel):
    entry_key: str
    title: str
    content: str
    category: str = "general"
    visibility: str = Field(default="public", examples=["public", "restricted", "narrator_only"])
    importance: int = Field(default=5, ge=0, le=10)
    tags: list[str] = Field(default_factory=list)


class ScenarioStudioGoalDraft(BaseModel):
    agent_id: str
    goal_key: str
    title: str
    description: str = ""
    priority: int = Field(default=5, ge=0, le=10)
    related_lorebook_keys: list[str] = Field(default_factory=list)
    related_entity_ids: list[str] = Field(default_factory=list)


class ScenarioStudioSkillDraft(BaseModel):
    agent_id: str
    skill_key: str
    title: str
    description: str = ""
    keywords: list[str] = Field(default_factory=list)
    procedure: list[str] = Field(default_factory=list)
    priority: int = Field(default=50, ge=0, le=100)
    related_goal_keys: list[str] = Field(default_factory=list)
    related_lorebook_keys: list[str] = Field(default_factory=list)
    related_entity_ids: list[str] = Field(default_factory=list)


class ScenarioStudioEntityStateDraft(BaseModel):
    agent_id: str
    entity_id: str
    entity_name: str = ""
    entity_type: str = "character"
    role: str = ""
    state_kind: str = Field(default="narrative_entity")
    attributes: dict[str, Any] = Field(default_factory=dict)
    notes: str = ""


class ScenarioStudioMemoryDraft(BaseModel):
    agent_id: str
    content: str
    memory_type: str = Field(default="semantic", examples=["raw", "episodic", "semantic", "core"])
    importance: float = Field(default=0.5, ge=0.0, le=1.0)
    emotional_weight: float = Field(default=0.0, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScenarioStudioRelationDraft(BaseModel):
    agent_id: str
    source_type: str
    source_id: str
    relation_type: str = "related_to"
    target_type: str
    target_id: str
    strength: float = Field(default=0.8, ge=0.0, le=1.0)
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)
    description: str = ""


class ScenarioStudioBuildRequest(BaseModel):
    world_id: str = Field(default="demo_world")
    title: str = "Untitled scenario"
    summary: str = ""
    agents: list[ScenarioStudioAgentDraft] = Field(default_factory=list)
    lorebook_entries: list[ScenarioStudioLoreDraft] = Field(default_factory=list)
    goals: list[ScenarioStudioGoalDraft] = Field(default_factory=list)
    procedural_skills: list[ScenarioStudioSkillDraft] = Field(default_factory=list)
    entity_states: list[ScenarioStudioEntityStateDraft] = Field(default_factory=list)
    memories: list[ScenarioStudioMemoryDraft] = Field(default_factory=list)
    knowledge_relations: list[ScenarioStudioRelationDraft] = Field(default_factory=list)
    auto_link_skills_to_goals: bool = True
    auto_link_goals_to_lore: bool = True
    include_demo_evaluation_stub: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScenarioStudioValidationMessage(BaseModel):
    level: str = Field(default="info", examples=["info", "warning", "error"])
    section: str = "general"
    message: str


class ScenarioStudioBuildResponse(BaseModel):
    world_id: str
    title: str
    valid: bool
    brain_pack: dict[str, Any]
    evaluation_pack: dict[str, Any] | None = None
    messages: list[ScenarioStudioValidationMessage] = Field(default_factory=list)
    import_endpoint_hint: str = "/brain-packs/import"


class ScenarioStudioSaveRequest(ScenarioStudioBuildRequest):
    filename: str = Field(default="scenario_studio_pack.json")
    overwrite: bool = False


class ScenarioStudioSaveResponse(ScenarioStudioBuildResponse):
    saved: bool = False
    path: str = ""
