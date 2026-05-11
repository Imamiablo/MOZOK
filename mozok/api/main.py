from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session

from mozok.agent.service import AgentService
from mozok.context.context_builder import ContextBuilder
from mozok.core.bot_core import BotCore, get_memory_service
from mozok.memory.short_term_memory import SHORT_TERM_MEMORY
from mozok.memory.maintenance_apply import MemoryMaintenanceApplyService
from mozok.memory.maintenance_suggestions import MemoryMaintenanceSuggestionService
from mozok.db.session import get_db
from mozok.schemas.chat import ChatRequest, ChatResponse
from mozok.schemas.context import ContextDebugRequest
from mozok.api.entity_state_routes import router as entity_state_router
from mozok.api.goal_routes import router as goal_router
from mozok.api.knowledge_relation_routes import router as knowledge_relation_router
from mozok.api.procedural_skill_routes import router as procedural_skill_router
from mozok.api.lorebook_routes import router as lorebook_router
from mozok.api.brain_pack_routes import router as brain_pack_router
from mozok.schemas.memory import (
    MemoryCreate,
    MemoryForgetRequest,
    MemoryForgetResponse,
    MemoryMaintenanceRequest,
    MemoryMaintenanceResponse,
    MemoryMaintenanceApplyRejectRequest,
    MemoryMaintenanceApplyRejectResponse,
    MemoryMaintenanceSuggestionsRequest,
    MemoryMaintenanceSuggestionsResponse,
    MemoryPolicyUpdate,
    MemoryRead,
    MemorySearchRequest,
    MemorySearchResult,
)

app = FastAPI(title="Mozok", version="0.2.0")

app.include_router(entity_state_router)
app.include_router(goal_router)
app.include_router(knowledge_relation_router)
app.include_router(procedural_skill_router)
app.include_router(lorebook_router)
app.include_router(brain_pack_router)

@app.get("/")
def root():
    return {
        "name": "Mozok",
        "status": "alive",
        "description": "Reusable bot-brain engine using PostgreSQL + FAISS.",
        "memory_model": ["raw", "episodic", "semantic", "core"],
    }


@app.post("/memories", response_model=MemoryRead)
def add_memory(data: MemoryCreate, db: Session = Depends(get_db)):
    memory = get_memory_service(db).add_memory(data)
    return MemoryRead.from_record(memory)


@app.post("/memories/search", response_model=list[MemorySearchResult])
def search_memories(data: MemorySearchRequest, db: Session = Depends(get_db)):
    return get_memory_service(db).search(
        agent_id=data.agent_id,
        query=data.query,
        limit=data.limit,
        memory_type=data.memory_type,
    )


@app.delete("/memories/{memory_id}")
def delete_memory(memory_id: int, db: Session = Depends(get_db)):
    ok = get_memory_service(db).soft_delete(memory_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Memory not found")
    return {"deleted": True, "memory_id": memory_id}


@app.post("/memories/{memory_id}/forget", response_model=MemoryForgetResponse)
def forget_memory(memory_id: int, data: MemoryForgetRequest, db: Session = Depends(get_db)):
    result = get_memory_service(db).forget_memory(
        memory_id=memory_id,
        action=data.action,
        reason=data.reason,
        decay_amount=data.decay_amount,
        rebuild_index=data.rebuild_index,
    )
    if not result["changed"] and result["message"] == "Memory not found.":
        raise HTTPException(status_code=404, detail="Memory not found")
    return MemoryForgetResponse(**result)


@app.post("/memories/rebuild-index")
def rebuild_index(db: Session = Depends(get_db)):
    count = get_memory_service(db).rebuild_index()
    return {"rebuilt": True, "indexed_memories": count}


@app.get("/agents/{agent_id}/memory-policy")
def get_agent_memory_policy(agent_id: str, db: Session = Depends(get_db)):
    return get_memory_service(db).get_memory_policy(agent_id)


@app.patch("/agents/{agent_id}/memory-policy")
def update_agent_memory_policy(agent_id: str, data: MemoryPolicyUpdate, db: Session = Depends(get_db)):
    policy = get_memory_service(db).update_memory_policy(agent_id, data.memory_policy)
    return {"agent_id": agent_id, "memory_policy": policy}


@app.post("/agents/{agent_id}/memory-maintenance", response_model=MemoryMaintenanceResponse)
def run_agent_memory_maintenance(
    agent_id: str,
    data: MemoryMaintenanceRequest | None = None,
    db: Session = Depends(get_db),
):
    request = data or MemoryMaintenanceRequest()
    return get_memory_service(db).run_maintenance(
        agent_id=agent_id,
        trigger=request.trigger,
        rebuild_index=request.rebuild_index,
    )


@app.post("/agents/{agent_id}/memory-maintenance/suggestions", response_model=MemoryMaintenanceSuggestionsResponse)
def preview_agent_memory_maintenance_suggestions(
    agent_id: str,
    data: MemoryMaintenanceSuggestionsRequest | None = None,
    db: Session = Depends(get_db),
):
    """Preview maintenance suggestions without changing SQL or FAISS.

    The endpoint is intentionally read-only. It can use deterministic rules,
    relation-aware protection, optional embedding clustering, and optional LLM
    explanation text, but it does not apply the suggestions.
    """

    request = data or MemoryMaintenanceSuggestionsRequest()
    memory_service = get_memory_service(db)
    return MemoryMaintenanceSuggestionService(
        db=db,
        embedding_service=memory_service.embedding_service,
    ).preview(agent_id=agent_id, request=request)


@app.post("/agents/{agent_id}/memory-maintenance/apply", response_model=MemoryMaintenanceApplyRejectResponse)
def apply_agent_memory_maintenance_suggestions(
    agent_id: str,
    data: MemoryMaintenanceApplyRejectRequest,
    db: Session = Depends(get_db),
):
    """Apply selected or all maintenance suggestions.

    This endpoint is suggestion-driven: clients should usually call the
    read-only suggestions endpoint first, review the suggestions, and pass the
    accepted suggestions here. Relation-aware protection is enforced by default.
    """

    memory_service = get_memory_service(db)
    return MemoryMaintenanceApplyService(db=db, memory_service=memory_service).apply_suggestions(
        agent_id=agent_id,
        request=data,
    )


@app.post("/agents/{agent_id}/memory-maintenance/reject", response_model=MemoryMaintenanceApplyRejectResponse)
def reject_agent_memory_maintenance_suggestions(
    agent_id: str,
    data: MemoryMaintenanceApplyRejectRequest,
    db: Session = Depends(get_db),
):
    """Reject selected or all maintenance suggestions without applying them.

    Rejection records a small note in the target memory metadata so future
    maintenance UI can show that the user declined the suggestion.
    """

    memory_service = get_memory_service(db)
    return MemoryMaintenanceApplyService(db=db, memory_service=memory_service).reject_suggestions(
        agent_id=agent_id,
        request=data,
    )


@app.post("/agents/{agent_id}/sessions/end", response_model=MemoryMaintenanceResponse)
def end_agent_session(
    agent_id: str,
    session_id: str | None = None,
    db: Session = Depends(get_db),
):
    # Ending a session should clear short-term RAM/context memory.
    # Long-term raw memories in PostgreSQL are handled by maintenance below.
    if session_id:
        cleared_short_term_messages = SHORT_TERM_MEMORY.clear_session(agent_id, session_id)
    else:
        cleared_short_term_messages = SHORT_TERM_MEMORY.clear_agent(agent_id)

    result = get_memory_service(db).end_session(agent_id=agent_id, rebuild_index=True)
    result.notes.append(f"Cleared {cleared_short_term_messages} short-term messages from RAM.")
    return result


@app.post("/debug/context")
def debug_context(data: ContextDebugRequest, db: Session = Depends(get_db)):
    """Build and return the exact context package for a chat turn without calling the LLM.

    Use this for future UI popups, debugging retrieval, checking short-term memory,
    and seeing which memories were removed by context deduplication.
    """

    memory_service = get_memory_service(db)
    agent = AgentService(db).get_or_create_default_agent(data.agent_id)
    context = ContextBuilder(db=db, memory_service=memory_service).build(
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
        allow_core_trimming=data.allow_core_trimming,
        token_estimation_model=data.token_estimation_model,
        section_budget_tokens=data.section_budget_tokens,
        compression_enabled=data.compression_enabled,
        short_term_summarization_enabled=data.short_term_summarization_enabled,
        budget_aware_graph_expansion=data.budget_aware_graph_expansion,
        include_goals=data.include_goals,
        goal_limit=data.goal_limit,
        goal_status=data.goal_status,
        include_procedural_skills=data.include_procedural_skills,
        procedural_skill_limit=data.procedural_skill_limit,
        procedural_skill_type=data.procedural_skill_type,
        procedural_skill_status=data.procedural_skill_status,
        select_relevant_procedural_skills=data.select_relevant_procedural_skills,
        procedural_skill_min_score=data.procedural_skill_min_score,
        procedural_skill_fallback_to_priority=data.procedural_skill_fallback_to_priority,
        include_knowledge_relations=data.include_knowledge_relations,
        knowledge_relation_limit=data.knowledge_relation_limit,
        knowledge_relation_world_id=data.knowledge_relation_world_id,
        knowledge_relation_source_type=data.knowledge_relation_source_type,
        knowledge_relation_source_id=data.knowledge_relation_source_id,
        knowledge_relation_target_type=data.knowledge_relation_target_type,
        knowledge_relation_target_id=data.knowledge_relation_target_id,
        knowledge_relation_type=data.knowledge_relation_type,
        include_related_knowledge_relations=data.include_related_knowledge_relations,
        related_knowledge_relation_limit=data.related_knowledge_relation_limit,
        world_id=data.world_id,
        lorebook_limit=data.lorebook_limit,
        include_public_lore=data.include_public_lore,
        include_narrator_only_lore=data.include_narrator_only_lore,
        include_entity_states=data.include_entity_states,
        entity_state_limit=data.entity_state_limit,
        entity_state_kind=data.entity_state_kind,
        entity_state_entity_id=data.entity_state_entity_id,
    )
    return context.to_debug_dict(
        include_full_prompt=data.include_full_prompt,
        prompt_preview_chars=data.prompt_preview_chars,
    )


@app.post("/chat", response_model=ChatResponse)
def chat(data: ChatRequest, db: Session = Depends(get_db)):
    try:
        return BotCore(db).chat(
            agent_id=data.agent_id,
            message=data.message,
            session_id=data.session_id,
            short_term_limit=data.short_term_limit,
            enforce_token_budget=data.enforce_token_budget,
            max_prompt_tokens=data.max_prompt_tokens,
            reserved_response_tokens=data.reserved_response_tokens,
            allow_core_trimming=data.allow_core_trimming,
            token_estimation_model=data.token_estimation_model,
            section_budget_tokens=data.section_budget_tokens,
            compression_enabled=data.compression_enabled,
            short_term_summarization_enabled=data.short_term_summarization_enabled,
            budget_aware_graph_expansion=data.budget_aware_graph_expansion,
            include_goals=data.include_goals,
            goal_limit=data.goal_limit,
            goal_status=data.goal_status,
            include_procedural_skills=data.include_procedural_skills,
            procedural_skill_limit=data.procedural_skill_limit,
            procedural_skill_type=data.procedural_skill_type,
            procedural_skill_status=data.procedural_skill_status,
            select_relevant_procedural_skills=data.select_relevant_procedural_skills,
            procedural_skill_min_score=data.procedural_skill_min_score,
            procedural_skill_fallback_to_priority=data.procedural_skill_fallback_to_priority,
            include_knowledge_relations=data.include_knowledge_relations,
            knowledge_relation_limit=data.knowledge_relation_limit,
            knowledge_relation_world_id=data.knowledge_relation_world_id,
            knowledge_relation_source_type=data.knowledge_relation_source_type,
            knowledge_relation_source_id=data.knowledge_relation_source_id,
            knowledge_relation_target_type=data.knowledge_relation_target_type,
            knowledge_relation_target_id=data.knowledge_relation_target_id,
            knowledge_relation_type=data.knowledge_relation_type,
            include_related_knowledge_relations=data.include_related_knowledge_relations,
            related_knowledge_relation_limit=data.related_knowledge_relation_limit,
            world_id=data.world_id,
            lorebook_limit=data.lorebook_limit,
            include_public_lore=data.include_public_lore,
            include_narrator_only_lore=data.include_narrator_only_lore,
            include_entity_states=data.include_entity_states,
            entity_state_limit=data.entity_state_limit,
            entity_state_kind=data.entity_state_kind,
            entity_state_entity_id=data.entity_state_entity_id,
        )
    except Exception as e:
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# --- MOZOK_BRAIN_PACK_IMPORT_BY_NAME_ROUTER START ---
# Local brain-pack import by safe name from data/brain_packs/.
# Keep /brain-packs/import for raw JSON-object imports.
from mozok.api.brain_pack_import_by_name_route import router as _mozok_brain_pack_import_by_name_router

app.include_router(_mozok_brain_pack_import_by_name_router)
# --- MOZOK_BRAIN_PACK_IMPORT_BY_NAME_ROUTER END ---

