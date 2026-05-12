from sqlalchemy.orm import Session

from mozok.agent.service import AgentService
from mozok.config import get_settings
from mozok.context.context_builder import ContextBuilder
from mozok.embeddings.factory import get_embedding_service
from mozok.faiss_index.store import FaissMemoryIndex
from mozok.llm.ollama_openai import OllamaOpenAIClient
from mozok.memory.service import MemoryService
from mozok.memory.short_term_memory import SHORT_TERM_MEMORY
from mozok.schemas.chat import ChatResponse
from mozok.schemas.memory import MemoryCreate
from mozok.perception.schemas import PerceptionEvent, PerceptionProfile
from mozok.reflection.schemas import ReflectionRequest
from mozok.reflection.service import ReflectionService


def get_memory_service(db: Session) -> MemoryService:
    settings = get_settings()
    embedding_service = get_embedding_service()
    vector_index = FaissMemoryIndex(
        index_path=settings.faiss_index_path,
        mapping_path=settings.faiss_mapping_path,
    )
    return MemoryService(db, embedding_service, vector_index)


class BotCore:
    """High-level bot core.

    This is what game/chat/desktop-pet adapters should eventually call.
    """

    def __init__(self, db: Session):
        self.db = db
        self.memory = get_memory_service(db)
        self.llm = OllamaOpenAIClient()
        self.agent_service = AgentService(db)
        self.context_builder = ContextBuilder(db=db, memory_service=self.memory)

    def chat(
        self,
        agent_id: str,
        message: str,
        session_id: str = "default",
        short_term_limit: int = 20,
        enforce_token_budget: bool = True,
        max_prompt_tokens: int = 6000,
        reserved_response_tokens: int = 1000,
        allow_core_trimming: bool = False,
        token_estimation_model: str = "generic",
        section_budget_tokens: dict[str, int] | None = None,
        compression_enabled: bool = True,
        short_term_summarization_enabled: bool = True,
        budget_aware_graph_expansion: bool = True,
        enable_cognitive_field: bool = False,
        sensory_inputs: list | None = None,
        perception_events: list[PerceptionEvent] | None = None,
        perception_profile: PerceptionProfile | None = None,
        attention_focus_keywords: list[str] | None = None,
        cognitive_max_candidates: int = 12,
        cognitive_broadcast_top_n: int = 3,
        cognitive_min_score: float = 0.0,
        enable_reflection_loop: bool = False,
        reflection_approval_mode: str = "manual_review",
        reflection_auto_apply: bool = False,
        reflection_store_proposals: bool = True,
        reflection_outcome: str = "unknown",
        reflection_feedback: str = "",
        include_goals: bool = True,
        goal_limit: int = 10,
        goal_status: str | None = None,
        include_procedural_skills: bool = True,
        procedural_skill_limit: int = 5,
        procedural_skill_type: str | None = None,
        procedural_skill_status: str | None = "active",
        select_relevant_procedural_skills: bool = False,
        procedural_skill_min_score: float = 1.0,
        procedural_skill_fallback_to_priority: bool = True,
        include_shared_procedural_skills: bool = False,
        include_knowledge_relations: bool = False,
        knowledge_relation_limit: int = 10,
        knowledge_relation_world_id: str | None = None,
        knowledge_relation_source_type: str | None = None,
        knowledge_relation_source_id: str | None = None,
        knowledge_relation_target_type: str | None = None,
        knowledge_relation_target_id: str | None = None,
        knowledge_relation_type: str | None = None,
        include_related_knowledge_relations: bool = False,
        related_knowledge_relation_limit: int = 10,
        knowledge_relation_traversal_depth: int = 1,
        knowledge_relation_traversal_token_budget: int | None = None,
        world_id: str = "default",
        lorebook_limit: int = 10,
        include_public_lore: bool = True,
        include_narrator_only_lore: bool = False,
        include_entity_states: bool = True,
        entity_state_limit: int = 10,
        entity_state_kind: str | None = None,
        entity_state_entity_id: str | None = None,
    ) -> ChatResponse:
        agent = self.agent_service.get_or_create_default_agent(agent_id)

        context = self.context_builder.build(
            agent=agent,
            user_message=message,
            session_id=session_id,
            short_term_limit=short_term_limit,
            enforce_token_budget=enforce_token_budget,
            max_prompt_tokens=max_prompt_tokens,
            reserved_response_tokens=reserved_response_tokens,
            allow_core_trimming=allow_core_trimming,
            token_estimation_model=token_estimation_model,
            section_budget_tokens=section_budget_tokens or {},
            compression_enabled=compression_enabled,
            short_term_summarization_enabled=short_term_summarization_enabled,
            budget_aware_graph_expansion=budget_aware_graph_expansion,
            enable_cognitive_field=enable_cognitive_field,
            sensory_inputs=sensory_inputs or [],
            perception_events=perception_events or [],
            perception_profile=perception_profile,
            attention_focus_keywords=attention_focus_keywords or [],
            cognitive_max_candidates=cognitive_max_candidates,
            cognitive_broadcast_top_n=cognitive_broadcast_top_n,
            cognitive_min_score=cognitive_min_score,
            include_goals=include_goals,
            goal_limit=goal_limit,
            goal_status=goal_status,
            include_procedural_skills=include_procedural_skills,
            procedural_skill_limit=procedural_skill_limit,
            procedural_skill_type=procedural_skill_type,
            procedural_skill_status=procedural_skill_status,
            select_relevant_procedural_skills=select_relevant_procedural_skills,
            procedural_skill_min_score=procedural_skill_min_score,
            procedural_skill_fallback_to_priority=procedural_skill_fallback_to_priority,
            include_shared_procedural_skills=include_shared_procedural_skills,
            include_knowledge_relations=include_knowledge_relations,
            knowledge_relation_limit=knowledge_relation_limit,
            knowledge_relation_world_id=knowledge_relation_world_id,
            knowledge_relation_source_type=knowledge_relation_source_type,
            knowledge_relation_source_id=knowledge_relation_source_id,
            knowledge_relation_target_type=knowledge_relation_target_type,
            knowledge_relation_target_id=knowledge_relation_target_id,
            knowledge_relation_type=knowledge_relation_type,
            include_related_knowledge_relations=include_related_knowledge_relations,
            related_knowledge_relation_limit=related_knowledge_relation_limit,
            knowledge_relation_traversal_depth=knowledge_relation_traversal_depth,
            knowledge_relation_traversal_token_budget=knowledge_relation_traversal_token_budget,
            world_id=world_id,
            lorebook_limit=lorebook_limit,
            include_public_lore=include_public_lore,
            include_narrator_only_lore=include_narrator_only_lore,
            include_entity_states=include_entity_states,
            entity_state_limit=entity_state_limit,
            entity_state_kind=entity_state_kind,
            entity_state_entity_id=entity_state_entity_id,
        )

        system_prompt = context.to_system_prompt()
        response_text = self.llm.chat(system_prompt=system_prompt, user_message=message)

        # Update short-term working memory after the model responds.
        SHORT_TERM_MEMORY.add_message(
            agent_id=agent_id,
            session_id=session_id,
            role="user",
            content=message,
        )
        SHORT_TERM_MEMORY.add_message(
            agent_id=agent_id,
            session_id=session_id,
            role="assistant",
            content=response_text,
        )

        reflection_report = None
        if enable_reflection_loop:
            reflection_report = ReflectionService(db=self.db, memory_service=self.memory).reflect(
                ReflectionRequest(
                    agent_id=agent_id,
                    session_id=session_id,
                    user_message=message,
                    assistant_response=response_text,
                    cognitive_field=context.cognitive_field.model_dump() if context.cognitive_field else None,
                    used_memory_ids=context.used_memory_ids(),
                    used_goal_ids=context.used_goal_ids(),
                    used_procedural_skill_ids=context.used_procedural_skill_ids(),
                    outcome=reflection_outcome,
                    feedback=reflection_feedback,
                    create_change_proposals=True,
                    approval_mode=reflection_approval_mode,
                    auto_apply=reflection_auto_apply,
                    store_proposals=reflection_store_proposals,
                )
            )

        # Raw dialogue is useful for later consolidation, but it should not be
        # treated as an important long-term fact. Maintenance can later summarize
        # raw dialogue into semantic memories and archive the noisy originals.
        self.memory.add_memory(
            MemoryCreate(
                agent_id=agent_id,
                session_id=session_id,
                content=f"User said: {message}",
                memory_type="raw",
                importance=2,
                metadata={"speaker": "user"},
            )
        )
        self.memory.add_memory(
            MemoryCreate(
                agent_id=agent_id,
                session_id=session_id,
                content=f"Bot replied: {response_text}",
                memory_type="raw",
                importance=2,
                metadata={"speaker": "bot"},
            )
        )

        return ChatResponse(
            agent_id=agent_id,
            session_id=session_id,
            response=response_text,
            used_memory_ids=context.used_memory_ids(),
            used_short_term_messages_count=context.used_short_term_count(),
            used_goal_ids=context.used_goal_ids(),
            used_goals_count=len(context.goal_items),
            used_procedural_skill_ids=context.used_procedural_skill_ids(),
            used_procedural_skills_count=len(context.procedural_skill_items),
            procedural_skill_selection=context.procedural_skill_selection,
            used_knowledge_relation_ids=context.used_knowledge_relation_ids(),
            used_knowledge_relations_count=len(context.knowledge_relation_items),
            explicit_knowledge_relation_ids=context.explicit_knowledge_relation_ids(),
            explicit_knowledge_relations_count=len(context.explicit_knowledge_relation_items),
            auto_expanded_knowledge_relation_ids=context.auto_expanded_knowledge_relation_ids(),
            auto_expanded_knowledge_relations_count=len(context.auto_expanded_knowledge_relation_items),
            used_lorebook_entry_ids=context.used_lorebook_entry_ids(),
            used_lorebook_entries_count=len(context.lorebook_items),
            used_entity_state_ids=context.used_entity_state_ids(),
            used_entity_states_count=len(context.entity_state_items),
            dedup_removed_memories_count=context.dedup_removed_count(),
            context_budget=context.context_budget.to_dict() if context.context_budget else None,
            cognitive_field=context.cognitive_field.model_dump() if context.cognitive_field else None,
            reflection_report=reflection_report.model_dump() if reflection_report else None,
        )
