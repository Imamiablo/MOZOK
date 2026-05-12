from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from mozok.agent.service import AgentService
from mozok.context.context_builder import ContextBuilder
from mozok.core.bot_core import get_memory_service
from mozok.db.session import get_db
from mozok.cognition.schemas import CognitiveFieldDebugRequest, CognitiveFieldReport

router = APIRouter(tags=["cognition"])


@router.post("/agents/{agent_id}/cognition/field/debug", response_model=CognitiveFieldReport)
def debug_agent_cognitive_field(agent_id: str, data: CognitiveFieldDebugRequest, db: Session = Depends(get_db)):
    """Run a read-only Cognitive Field pass without calling the LLM."""
    agent = AgentService(db).get_or_create_default_agent(agent_id)
    context = ContextBuilder(db=db, memory_service=get_memory_service(db)).build(
        agent=agent,
        user_message=data.message,
        session_id=data.session_id,
        short_term_limit=data.short_term_limit,
        core_limit=data.core_limit,
        semantic_limit=data.semantic_limit,
        episodic_limit=data.episodic_limit,
        raw_limit=data.raw_limit,
        update_memory_access=False,
        enforce_token_budget=data.enforce_token_budget,
        max_prompt_tokens=data.max_prompt_tokens,
        reserved_response_tokens=data.reserved_response_tokens,
        include_goals=data.include_goals,
        goal_limit=data.goal_limit,
        include_procedural_skills=data.include_procedural_skills,
        procedural_skill_limit=data.procedural_skill_limit,
        select_relevant_procedural_skills=data.select_relevant_procedural_skills,
        include_shared_procedural_skills=data.include_shared_procedural_skills,
        include_knowledge_relations=data.include_knowledge_relations,
        knowledge_relation_limit=data.knowledge_relation_limit,
        include_related_knowledge_relations=data.include_related_knowledge_relations,
        related_knowledge_relation_limit=data.related_knowledge_relation_limit,
        knowledge_relation_traversal_depth=data.knowledge_relation_traversal_depth,
        world_id=data.world_id,
        lorebook_limit=data.lorebook_limit,
        include_public_lore=data.include_public_lore,
        include_narrator_only_lore=data.include_narrator_only_lore,
        include_entity_states=data.include_entity_states,
        entity_state_limit=data.entity_state_limit,
        enable_cognitive_field=True,
        sensory_inputs=data.sensory_inputs,
        attention_focus_keywords=data.attention_focus_keywords,
        cognitive_max_candidates=data.cognitive_max_candidates,
        cognitive_broadcast_top_n=data.cognitive_broadcast_top_n,
        cognitive_min_score=data.cognitive_min_score,
    )
    assert context.cognitive_field is not None
    return context.cognitive_field
