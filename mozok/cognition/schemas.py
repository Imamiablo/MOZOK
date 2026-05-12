from __future__ import annotations

from typing import Any, Literal
from pydantic import BaseModel, Field


class SensoryInput(BaseModel):
    """Generic external/internal signal that can influence attention."""
    channel: str = Field(..., examples=["vision", "hearing", "body", "ui", "world_event"])
    content: str = Field(..., examples=["A metallic sound echoes from the old well."])
    intensity: float = Field(default=1.0, ge=0.0, le=10.0, description="Signal strength before attention filtering.")
    attention: float = Field(default=1.0, ge=0.0, le=10.0, description="How much this signal is currently attended to.")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="How reliable this signal is considered to be.")
    source: str = Field(default="external", examples=["external", "internal", "tool", "game"])
    tags: list[str] = Field(default_factory=list, examples=[["old well", "metallic sound"]])
    metadata: dict[str, Any] = Field(default_factory=dict)


class CognitiveFieldScore(BaseModel):
    attention_weight: float = 0.0
    sensory_weight: float = 0.0
    memory_resonance: float = 0.0
    goal_relevance: float = 0.0
    emotional_weight: float = 0.0
    procedural_skill_relevance: float = 0.0
    relation_graph_support: float = 0.0
    contradiction_penalty: float = 0.0
    risk_penalty: float = 0.0
    confidence: float = 0.0
    final_score: float = 0.0


class CandidateThought(BaseModel):
    thought_id: str
    thought_type: Literal[
        "respond_to_user",
        "attend_sensory_signal",
        "recall_memory",
        "pursue_goal",
        "use_skill",
        "track_entity_state",
        "use_lore",
        "follow_relation",
    ]
    label: str
    content: str
    source: str
    source_id: str | None = None
    sensory_channel: str | None = None
    focus_tags: list[str] = Field(default_factory=list)
    score: CognitiveFieldScore = Field(default_factory=CognitiveFieldScore)
    evidence: list[str] = Field(default_factory=list)
    broadcast_recommendation: str = "Use as soft attention guidance only."


class ConsciousBroadcast(BaseModel):
    selected_thought_id: str | None = None
    selected_label: str | None = None
    selected_type: str | None = None
    summary: str = ""
    attention_focus: list[str] = Field(default_factory=list)
    top_thought_ids: list[str] = Field(default_factory=list)
    working_memory_line: str = ""
    update_recommendations: list[str] = Field(default_factory=list)
    prompt_guidance: str = ""


class CognitiveFieldReport(BaseModel):
    enabled: bool = True
    read_only: bool = True
    architecture: str = "resonance_competition_broadcast"
    note: str = "Functional cognitive-field report for attention, competition, and broadcast selection."
    candidate_count: int = 0
    broadcast_top_n: int = 3
    winning_thought_id: str | None = None
    winning_score: float | None = None
    candidates: list[CandidateThought] = Field(default_factory=list)
    broadcast: ConsciousBroadcast = Field(default_factory=ConsciousBroadcast)
    attention_report: dict[str, Any] = Field(default_factory=dict)
    sensory_report: dict[str, Any] = Field(default_factory=dict)


class CognitiveFieldConfig(BaseModel):
    enable_cognitive_field: bool = Field(default=False, description="Run Cognitive Field MVP and expose a broadcast report.")
    sensory_inputs: list[SensoryInput] = Field(default_factory=list)
    attention_focus_keywords: list[str] = Field(default_factory=list)
    cognitive_max_candidates: int = Field(default=12, ge=1, le=100)
    cognitive_broadcast_top_n: int = Field(default=3, ge=1, le=10)
    cognitive_min_score: float = Field(default=0.0, ge=-100.0, le=100.0)


class CognitiveFieldDebugRequest(BaseModel):
    """Dedicated read-only debug request for Cognitive Field MVP."""
    message: str = Field(..., examples=["What do you know about the old well and the sound behind it?"])
    session_id: str = Field(default="default")
    world_id: str = Field(default="default")
    short_term_limit: int = Field(default=20, ge=0, le=40)
    core_limit: int = Field(default=10, ge=0, le=50)
    semantic_limit: int = Field(default=6, ge=0, le=50)
    episodic_limit: int = Field(default=4, ge=0, le=50)
    raw_limit: int = Field(default=0, ge=0, le=50)
    include_goals: bool = Field(default=True)
    goal_limit: int = Field(default=10, ge=0, le=50)
    include_procedural_skills: bool = Field(default=True)
    procedural_skill_limit: int = Field(default=5, ge=0, le=50)
    select_relevant_procedural_skills: bool = Field(default=True)
    include_shared_procedural_skills: bool = Field(default=False)
    include_knowledge_relations: bool = Field(default=True)
    knowledge_relation_limit: int = Field(default=10, ge=0, le=50)
    include_related_knowledge_relations: bool = Field(default=True)
    related_knowledge_relation_limit: int = Field(default=10, ge=0, le=50)
    knowledge_relation_traversal_depth: int = Field(default=2, ge=1, le=5)
    lorebook_limit: int = Field(default=10, ge=0, le=50)
    include_public_lore: bool = Field(default=True)
    include_narrator_only_lore: bool = Field(default=False)
    include_entity_states: bool = Field(default=True)
    entity_state_limit: int = Field(default=10, ge=0, le=50)
    enforce_token_budget: bool = Field(default=True)
    max_prompt_tokens: int = Field(default=6000, ge=100, le=200000)
    reserved_response_tokens: int = Field(default=1000, ge=0, le=100000)
    sensory_inputs: list[SensoryInput] = Field(default_factory=list)
    attention_focus_keywords: list[str] = Field(default_factory=list)
    cognitive_max_candidates: int = Field(default=12, ge=1, le=100)
    cognitive_broadcast_top_n: int = Field(default=3, ge=1, le=10)
    cognitive_min_score: float = Field(default=0.0, ge=-100.0, le=100.0)
