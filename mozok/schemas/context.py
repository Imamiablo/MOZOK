from pydantic import BaseModel, Field


class ContextDebugRequest(BaseModel):
    """Request body for /debug/context.

    This builds the same context package that /chat would use, but does not call
    the LLM and does not write new memories.
    """

    agent_id: str = Field(..., examples=["cat_001"])
    message: str = Field(..., examples=["What do you remember about my cats?"])
    session_id: str = Field(
        "default",
        description="Conversation/session key for short-term working memory.",
        examples=["default", "game_session_001"],
    )
    short_term_limit: int = Field(
        20,
        ge=0,
        le=40,
        description="How many recent short-term messages to include in debug context.",
    )
    core_limit: int = Field(default=10, ge=0, le=50)
    semantic_limit: int = Field(default=6, ge=0, le=50)
    episodic_limit: int = Field(default=4, ge=0, le=50)
    raw_limit: int = Field(default=0, ge=0, le=50)


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

    include_full_prompt: bool = Field(
        default=True,
        description="If true, response includes the exact full system prompt that would be sent to the LLM.",
    )
    prompt_preview_chars: int = Field(
        default=2000,
        ge=0,
        le=20000,
        description="How many characters to include in prompt_preview.",
    )
