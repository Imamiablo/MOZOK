from pydantic import BaseModel, Field

from mozok.cognition.schemas import SensoryInput


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

    include_shared_procedural_skills: bool = Field(
        default=False,
        description="If true, include shared library procedural skills under __shared__ as fallbacks. Local skills override shared skills with the same key.",
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
        description="Maximum number of auto-expanded knowledge relations to include.",
    )
    knowledge_relation_traversal_depth: int = Field(
        default=1,
        ge=1,
        le=5,
        description=(
            "How many graph hops to use for related knowledge-relation expansion. "
            "1 keeps legacy one-hop behaviour; 2+ enables Knowledge Relations V3 multi-hop traversal."
        ),
    )
    knowledge_relation_traversal_token_budget: int | None = Field(
        default=None,
        ge=1,
        le=20000,
        description=(
            "Optional approximate token budget for multi-hop relation traversal. "
            "Null uses the knowledge_relations section budget when budget-aware expansion is enabled."
        ),
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
    token_estimation_model: str = Field(
        default="generic",
        description=(
            "Cheap token-estimation profile to use for budget reports, e.g. generic, qwen, llama, gemma, japanese. "
            "This is not a real tokenizer; it adjusts the character-per-token estimate."
        ),
        examples=["generic", "qwen3-coder:30b", "llama3.1", "japanese"],
    )
    section_budget_tokens: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Optional per-section soft token budgets. Keys include goals, procedural_skills, entity_states, "
            "lorebook, knowledge_relations, core, short_term, semantic, episodic, raw. "
            "Omitted keys use safe default shares of the available prompt budget."
        ),
        examples=[{"short_term": 500, "semantic": 700, "knowledge_relations": 250}],
    )
    compression_enabled: bool = Field(
        default=True,
        description="If true, compress oversized context items before dropping them from the prompt.",
    )
    short_term_summarization_enabled: bool = Field(
        default=True,
        description="If true, summarise older short-term messages into one compact note when the prompt is over budget.",
    )
    budget_aware_graph_expansion: bool = Field(
        default=True,
        description="If true, cap knowledge-relation graph expansion using the knowledge_relations section budget.",
    )

    enable_cognitive_field: bool = Field(
        default=False,
        description=(
            "If true, run the Cognitive Field MVP: candidate thoughts compete by attention, sensory weight, "
            "memory resonance, goal relevance, skill relevance, contradiction penalties, and risk penalties."
        ),
    )
    sensory_inputs: list[SensoryInput] = Field(
        default_factory=list,
        description="Optional sensory/tool/world signals that can compete for attention this turn.",
    )
    attention_focus_keywords: list[str] = Field(
        default_factory=list,
        description="Optional deliberate attention focus keywords for the Cognitive Field.",
    )
    cognitive_max_candidates: int = Field(default=12, ge=1, le=100)
    cognitive_broadcast_top_n: int = Field(default=3, ge=1, le=10)
    cognitive_min_score: float = Field(default=0.0, ge=-100.0, le=100.0)

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
