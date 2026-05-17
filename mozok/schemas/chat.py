from typing import Any

from pydantic import BaseModel, Field

from mozok.cognition.schemas import SensoryInput
from mozok.perception.schemas import PerceptionEvent, PerceptionProfile
from mozok.change_proposals.schemas import ApprovalMode
from mozok.action_planning.schemas import ActionKind, ActionToolSpec


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
    llm_model: str | None = Field(
        default=None,
        description="Optional exact model name for this LLM call. When omitted, llm_model_role is resolved through server configuration.",
        examples=["qwen2.5-coder:32b"],
    )
    llm_model_role: str | None = Field(
        default=None,
        description="Optional model role such as chat, scene, semantic, fast, reasoning, summarizer, or maintenance.",
        examples=["scene", "semantic", "fast"],
    )

    agent_mode: str | None = Field(
        default=None,
        description="Optional operating mode override, e.g. assistant, roleplay_character, simulacra_npc, narrator, world_director, tool_agent. Null resolves from agent metadata or assistant default.",
        examples=["simulacra_npc"],
    )
    apply_agent_mode_defaults: bool = Field(
        default=True,
        description="If true, resolved mode defaults can influence narrator-lore access, entity-state filtering, and cognitive/perception/reflection defaults.",
    )
    agent_mode_profile_overrides: dict[str, Any] = Field(
        default_factory=dict,
        description="Optional one-request overrides for the resolved AgentModeProfile. Prefer scenario metadata for persistent defaults.",
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
        description="Optional direct sensory/tool/world signals that can compete for attention this turn.",
    )
    perception_events: list[PerceptionEvent] = Field(
        default_factory=list,
        description="Optional adapter-neutral events to compile into sensory inputs before Cognitive Field scoring.",
    )
    perception_profile: PerceptionProfile = Field(
        default_factory=PerceptionProfile,
        description="Optional policy for compiling perception_events into sensory inputs.",
    )
    attention_focus_keywords: list[str] = Field(
        default_factory=list,
        description="Optional deliberate attention focus keywords for the Cognitive Field.",
    )
    cognitive_max_candidates: int = Field(default=12, ge=1, le=100)
    cognitive_broadcast_top_n: int = Field(default=3, ge=1, le=10)
    cognitive_min_score: float = Field(default=0.0, ge=-100.0, le=100.0)


    enable_self_model: bool = Field(
        default=False,
        description="If true, build a functional self-model preview for this chat turn and inject it into the prompt/action planning/reflection flow.",
    )
    include_self_model_in_prompt: bool = Field(
        default=True,
        description="If true and enable_self_model is true, include the self-model prompt block before the LLM response.",
    )
    self_model_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    self_model_uncertainty: float | None = Field(default=None, ge=0.0, le=1.0)

    enable_action_planning: bool = Field(
        default=False,
        description="If true, plan adapter-owned action intents for this chat turn after cognitive/self-model context is available.",
    )
    available_tools: list[ActionToolSpec] = Field(default_factory=list)
    allowed_action_kinds: list[ActionKind] = Field(default_factory=list)
    execute_selected_action: bool = Field(
        default=False,
        description="If true, queue the selected ready action through Action Execution Layer MVP. External adapters still own real execution.",
    )
    action_execution_approval_granted: bool = Field(default=False)

    enable_reflection_loop: bool = Field(
        default=False,
        description="If true, run the post-turn reflection loop after the assistant response and create safe change proposals.",
    )
    reflection_approval_mode: ApprovalMode = Field(
        default="manual_review",
        description="How reflection-created proposals should be handled: manual_review, apply_low_risk, auto_with_rollback, or dry_run_only.",
    )
    reflection_auto_apply: bool = Field(
        default=False,
        description="If true, immediately run the configured approval policy after creating reflection proposals.",
    )
    reflection_store_proposals: bool = Field(
        default=True,
        description="If true, store reflection proposals under the agent's change proposal list.",
    )
    reflection_outcome: str = Field(
        default="unknown",
        description="Optional caller-provided outcome hint for the turn: unknown, success, neutral, or failure.",
    )
    reflection_feedback: str = Field(default="", description="Optional explicit feedback used by the reflection loop.")


class ChatResponse(BaseModel):
    agent_id: str
    session_id: str
    response: str
    llm_model: str | None = None
    llm_model_role: str | None = None
    agent_mode: dict[str, Any] | None = None
    agent_mode_resolution: dict[str, Any] | None = None
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
    cognitive_field: dict[str, Any] | None = None
    self_model: dict[str, Any] | None = None
    action_plan: dict[str, Any] | None = None
    action_execution: dict[str, Any] | None = None
    reflection_report: dict[str, Any] | None = None
