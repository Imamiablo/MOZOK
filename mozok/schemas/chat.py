from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    agent_id: str = Field(..., examples=["cat_001"])
    message: str
    session_id: str = Field(
        "default",
        description="Conversation/session key for short-term working memory.",
        examples=["default", "game_session_001"],
    )
    short_term_limit: int = Field(
        20,
        ge=0,
        le=40,
        description="How many recent short-term messages to include in the prompt. Use 0 to disable.",
    )


    include_goals: bool = Field(
        default=True,
        description="If true, include active goals/plans for this agent in the prompt.",
    )
    goal_limit: int = Field(
        default=10,
        ge=0,
        le=50,
        description="How many goals/plans to include. Use 0 to disable goal context.",
    )
    goal_status: str | None = Field(
        default=None,
        description="Optional goal status filter, e.g. active, blocked, completed. Null includes all active goals.",
        examples=["active"],
    )

    include_procedural_skills: bool = Field(
        default=True,
        description="If true, include active procedural skills / behavior strategies for this agent in the prompt.",
    )
    procedural_skill_limit: int = Field(
        default=5,
        ge=0,
        le=50,
        description="How many procedural skills to include. Use 0 to disable procedural skill context.",
    )
    procedural_skill_type: str | None = Field(
        default=None,
        description="Optional procedural skill type filter, e.g. conversation, narration, teaching.",
        examples=["conversation"],
    )
    procedural_skill_status: str | None = Field(
        default="active",
        description="Optional procedural skill status filter, usually active.",
        examples=["active"],
    )
    select_relevant_procedural_skills: bool = Field(
        default=False,
        description=(
            "If true, score and select procedural skills by trigger keywords, active goals, "
            "selected lorebook entries, and selected entity-state IDs instead of taking only top priority skills."
        ),
    )
    procedural_skill_min_score: float = Field(
        default=1.0,
        ge=0.0,
        le=100.0,
        description="Minimum deterministic relevance score required when select_relevant_procedural_skills is true.",
    )
    procedural_skill_fallback_to_priority: bool = Field(
        default=True,
        description="If true and no skill matches relevance filters, fall back to top-priority active skills.",
    )

    include_knowledge_relations: bool = Field(
        default=False,
        description="If true, include knowledge relation graph edges for this agent in the prompt.",
    )
    knowledge_relation_limit: int = Field(
        default=10,
        ge=0,
        le=50,
        description="How many knowledge relations to include. Use 0 to disable relation context.",
    )
    knowledge_relation_world_id: str | None = Field(
        default=None,
        description="Optional world filter for knowledge relations. Null uses world_id.",
        examples=["default", "from_like_world"],
    )
    knowledge_relation_source_type: str | None = Field(default=None, examples=["goal", "memory", "lorebook"])
    knowledge_relation_source_id: str | None = Field(default=None, examples=["hide_tunnel_secret", "42", "old_well"])
    knowledge_relation_target_type: str | None = Field(default=None, examples=["lorebook", "entity_state", "goal"])
    knowledge_relation_target_id: str | None = Field(default=None, examples=["old_well", "17"])
    knowledge_relation_type: str | None = Field(default=None, examples=["depends_on", "evidence_for", "contradicts"])
    include_related_knowledge_relations: bool = Field(
        default=False,
        description=(
            "If true, add direct one-hop knowledge relations touching goals, lorebook entries, "
            "entity states, or memories already selected for this context."
        ),
    )
    related_knowledge_relation_limit: int = Field(
        default=10,
        ge=0,
        le=50,
        description="Maximum number of auto-expanded one-hop knowledge relations to include.",
    )

    world_id: str = Field(
        "default",
        description="Lorebook world/campaign ID to use when selecting world knowledge.",
        examples=["default", "from_series_world"],
    )
    lorebook_limit: int = Field(
        default=10,
        ge=0,
        le=50,
        description="How many lorebook entries to include in the prompt. Use 0 to disable lorebook context.",
    )
    include_public_lore: bool = Field(
        default=True,
        description="If true, include public lorebook entries for this world.",
    )
    include_narrator_only_lore: bool = Field(
        default=False,
        description="If true, include narrator_only lorebook entries. Keep false for normal NPCs/assistants.",
    )

    include_entity_states: bool = Field(
        default=True,
        description="If true, include active EntityState records for this agent in the prompt.",
    )
    entity_state_limit: int = Field(
        default=10,
        ge=0,
        le=50,
        description="How many EntityState records to include. Use 0 to disable entity-state context.",
    )
    entity_state_kind: str | None = Field(
        default=None,
        description="Optional EntityState kind filter, e.g. social_relationship, assistant_user_profile, narrative_entity.",
        examples=["social_relationship"],
    )
    entity_state_entity_id: str | None = Field(
        default=None,
        description="Optional entity_id filter for EntityState context.",
        examples=["npc_alice"],
    )

    enforce_token_budget: bool = Field(
        default=True,
        description="If true, trim selected context so the prompt stays within the configured approximate token budget.",
    )
    max_prompt_tokens: int = Field(
        default=6000,
        ge=100,
        le=200000,
        description="Approximate total model-side budget for prompt + reserved response.",
    )
    reserved_response_tokens: int = Field(
        default=1000,
        ge=0,
        le=100000,
        description="Approximate tokens reserved for the model response. The prompt target is max_prompt_tokens - reserved_response_tokens.",
    )
    allow_core_trimming: bool = Field(
        default=False,
        description="If false, core/profile memories are protected from token-budget trimming.",
    )


class ChatResponse(BaseModel):
    agent_id: str
    session_id: str
    response: str
    used_memory_ids: list[int]
    used_short_term_messages_count: int = 0
    used_goal_ids: list[int] = Field(default_factory=list)
    used_goals_count: int = 0
    used_procedural_skill_ids: list[int] = Field(default_factory=list)
    used_procedural_skills_count: int = 0
    procedural_skill_selection: list[dict[str, Any]] = Field(default_factory=list)
    used_knowledge_relation_ids: list[int] = Field(default_factory=list)
    used_knowledge_relations_count: int = 0
    explicit_knowledge_relation_ids: list[int] = Field(default_factory=list)
    explicit_knowledge_relations_count: int = 0
    auto_expanded_knowledge_relation_ids: list[int] = Field(default_factory=list)
    auto_expanded_knowledge_relations_count: int = 0
    used_lorebook_entry_ids: list[int] = Field(default_factory=list)
    used_lorebook_entries_count: int = 0
    used_entity_state_ids: list[int] = Field(default_factory=list)
    used_entity_states_count: int = 0
    dedup_removed_memories_count: int = 0
    context_budget: dict[str, Any] | None = None
