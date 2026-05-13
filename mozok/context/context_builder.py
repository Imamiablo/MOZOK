from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from mozok.db.models import AgentRecord, MemoryRecord
from mozok.context.dedup import ContextMemoryDeduplicator, DedupRemovedMemory
from mozok.context.token_budget import ContextBudgeter, ContextBudgetPolicy, ContextBudgetReport, context_item_key, estimate_tokens
from mozok.memory.policy import MEMORY_LEVEL_CORE
from mozok.memory.service import MemoryService
from mozok.memory.short_term_memory import SHORT_TERM_MEMORY, ShortTermMessage
from mozok.entity_state.service import EntityStateService, format_entity_state_for_prompt_line, reads_from_records
from mozok.schemas.goals import AgentGoalRead
from mozok.goals.service import GoalService, format_goal_for_prompt_line, reads_from_records as goal_reads_from_records
from mozok.knowledge_relations.service import KnowledgeRelationService, format_knowledge_relation_for_prompt_line, reads_from_records as knowledge_relation_reads_from_records
from mozok.procedural_skills.service import ProceduralSkillService, format_procedural_skill_for_prompt_line, reads_from_records as procedural_skill_reads_from_records
from mozok.lorebook.schemas import LorebookContextItem
from mozok.lorebook.service import LorebookService, format_lorebook_context
from mozok.schemas.entity_state import EntityStateRead
from mozok.schemas.knowledge_relations import KnowledgeGraphRootNode, KnowledgeRelationGraphDebugRequest, KnowledgeRelationRead
from mozok.schemas.procedural_skills import AgentProceduralSkillRead
from mozok.cognition.schemas import CognitiveFieldReport, SensoryInput
from mozok.cognition.service import CognitiveFieldService
from mozok.perception.schemas import PerceptionEvent, PerceptionProfile, PerceptionReport
from mozok.perception.service import PerceptionCompiler
from mozok.agent_modes.schemas import AgentModeProfile
from mozok.agent_modes.service import AgentModeService
from mozok.schemas.memory import MemorySearchResult

def _memory_reranking_final_score(memory: MemorySearchResult) -> float | None:
    """Return the transient reranking final score attached to a memory result.

    Reranking metadata is request-local debug/runtime metadata. It is not written
    back to SQL or FAISS. Missing or malformed scores are treated as absent so
    older memory results keep their existing order.
    """

    metadata = getattr(memory, "metadata", None)
    if not isinstance(metadata, dict):
        return None

    reranking = metadata.get("_reranking")
    if not isinstance(reranking, dict):
        return None

    try:
        return float(reranking.get("final_score"))
    except (TypeError, ValueError):
        return None


def _sort_memory_search_results_by_reranking_score(
    memories: list[MemorySearchResult],
) -> list[MemorySearchResult]:
    """Return memories ordered by reranking score, best first.

    Items without reranking metadata stay after scored items. Ties preserve the
    existing order, which keeps behaviour stable for older code paths.
    """

    indexed_memories = list(enumerate(memories))

    def sort_key(indexed_memory: tuple[int, MemorySearchResult]) -> tuple[bool, float, int]:
        original_index, memory = indexed_memory
        final_score = _memory_reranking_final_score(memory)
        if final_score is None:
            return (True, 0.0, original_index)
        return (False, -final_score, original_index)

    return [memory for _, memory in sorted(indexed_memories, key=sort_key)]



@dataclass
class ContextPackage:
    """Structured context prepared for the LLM.

    The important idea:
    BotCore should not manually decide which memories go into the prompt.
    BotCore asks ContextBuilder for a ready context package.
    """

    agent_id: str
    session_id: str
    system_prompt: str
    agent_name: str
    agent_description: str
    agent_personality: str
    current_user_message: str

    short_term_messages: list[ShortTermMessage] = field(default_factory=list)
    core_memories: list[MemoryRecord] = field(default_factory=list)
    semantic_memories: list[MemorySearchResult] = field(default_factory=list)
    episodic_memories: list[MemorySearchResult] = field(default_factory=list)
    raw_memories: list[MemorySearchResult] = field(default_factory=list)
    goal_items: list[AgentGoalRead] = field(default_factory=list)
    procedural_skill_items: list[AgentProceduralSkillRead] = field(default_factory=list)
    procedural_skill_selection: list[dict] = field(default_factory=list)
    knowledge_relation_items: list[KnowledgeRelationRead] = field(default_factory=list)
    explicit_knowledge_relation_items: list[KnowledgeRelationRead] = field(default_factory=list)
    auto_expanded_knowledge_relation_items: list[KnowledgeRelationRead] = field(default_factory=list)
    lorebook_items: list[LorebookContextItem] = field(default_factory=list)
    entity_state_items: list[EntityStateRead] = field(default_factory=list)
    dedup_removed_memories: list[DedupRemovedMemory] = field(default_factory=list)
    context_budget: ContextBudgetReport | None = None
    compressed_item_text: dict[str, str] = field(default_factory=dict)
    budget_aware_graph_expansion: dict = field(default_factory=dict)
    cognitive_field: CognitiveFieldReport | None = None
    perception_report: PerceptionReport | None = None
    agent_mode_profile: AgentModeProfile | None = None
    agent_mode_resolution: dict = field(default_factory=dict)
    self_model: dict | None = None
    self_model_prompt_block: str = ""
    action_plan: dict | None = None

    # Debug-only snapshots used to explain the context assembly pipeline.
    # These are copies of earlier stages so later budget trimming can mutate the
    # final prompt lists without hiding what happened before.
    retrieved_short_term_messages: list[ShortTermMessage] = field(default_factory=list)
    retrieved_core_memories: list[MemoryRecord] = field(default_factory=list)
    retrieved_semantic_memories: list[MemorySearchResult] = field(default_factory=list)
    retrieved_episodic_memories: list[MemorySearchResult] = field(default_factory=list)
    retrieved_raw_memories: list[MemorySearchResult] = field(default_factory=list)
    retrieved_goal_items: list[AgentGoalRead] = field(default_factory=list)
    retrieved_procedural_skill_items: list[AgentProceduralSkillRead] = field(default_factory=list)
    retrieved_procedural_skill_selection: list[dict] = field(default_factory=list)
    retrieved_knowledge_relation_items: list[KnowledgeRelationRead] = field(default_factory=list)
    retrieved_lorebook_items: list[LorebookContextItem] = field(default_factory=list)
    retrieved_entity_state_items: list[EntityStateRead] = field(default_factory=list)

    post_dedup_short_term_messages: list[ShortTermMessage] = field(default_factory=list)
    post_dedup_core_memories: list[MemoryRecord] = field(default_factory=list)
    post_dedup_semantic_memories: list[MemorySearchResult] = field(default_factory=list)
    post_dedup_episodic_memories: list[MemorySearchResult] = field(default_factory=list)
    post_dedup_raw_memories: list[MemorySearchResult] = field(default_factory=list)
    post_dedup_goal_items: list[AgentGoalRead] = field(default_factory=list)
    post_dedup_procedural_skill_items: list[AgentProceduralSkillRead] = field(default_factory=list)
    post_dedup_procedural_skill_selection: list[dict] = field(default_factory=list)
    post_dedup_knowledge_relation_items: list[KnowledgeRelationRead] = field(default_factory=list)
    post_dedup_lorebook_items: list[LorebookContextItem] = field(default_factory=list)
    post_dedup_entity_state_items: list[EntityStateRead] = field(default_factory=list)

    def used_memory_ids(self) -> list[int]:
        """Return IDs of long-term memories included in this context."""

        ids: list[int] = []

        ids.extend(memory.id for memory in self.core_memories)
        ids.extend(memory.id for memory in self.semantic_memories)
        ids.extend(memory.id for memory in self.episodic_memories)
        ids.extend(memory.id for memory in self.raw_memories)

        # Keep order but remove duplicates.
        return list(dict.fromkeys(ids))

    def used_short_term_count(self) -> int:
        return len(self.short_term_messages)

    def used_goal_ids(self) -> list[int]:
        """Return goal IDs included in this context."""

        return list(dict.fromkeys(int(item.id) for item in self.goal_items if item.id is not None))

    def used_procedural_skill_ids(self) -> list[int]:
        """Return procedural skill IDs included in this context."""

        return list(dict.fromkeys(int(item.id) for item in self.procedural_skill_items if item.id is not None))

    def used_knowledge_relation_ids(self) -> list[int]:
        """Return knowledge relation IDs included in this context."""

        return list(dict.fromkeys(int(item.id) for item in self.knowledge_relation_items if item.id is not None))

    def explicit_knowledge_relation_ids(self) -> list[int]:
        return list(dict.fromkeys(int(item.id) for item in self.explicit_knowledge_relation_items if item.id is not None))

    def auto_expanded_knowledge_relation_ids(self) -> list[int]:
        return list(dict.fromkeys(int(item.id) for item in self.auto_expanded_knowledge_relation_items if item.id is not None))

    def used_lorebook_entry_ids(self) -> list[int]:
        """Return lorebook entry IDs included in this context."""

        return list(dict.fromkeys(int(item.lorebook_entry_id) for item in self.lorebook_items))

    def used_entity_state_ids(self) -> list[int]:
        """Return entity-state IDs included in this context."""

        return list(dict.fromkeys(int(item.id) for item in self.entity_state_items if item.id is not None))

    def dedup_removed_count(self) -> int:
        return len(self.dedup_removed_memories)

    def dedup_removed_memory_ids(self) -> list[int]:
        return [item.removed_id for item in self.dedup_removed_memories]

    def pipeline_steps(self) -> list[dict]:
        """Explain how the final prompt context was assembled.

        This is mostly for /debug/context and a future UI popup. It separates
        the stages that were previously mixed together in one response:
        retrieval -> deduplication -> token-budget trimming -> final prompt.
        """

        final_prompt = self.to_system_prompt()
        final_estimated_tokens = estimate_tokens(final_prompt)

        retrieved_counts = self._stage_counts(
            short_term_messages=self.retrieved_short_term_messages,
            core_memories=self.retrieved_core_memories,
            semantic_memories=self.retrieved_semantic_memories,
            episodic_memories=self.retrieved_episodic_memories,
            raw_memories=self.retrieved_raw_memories,
            goal_items=self.retrieved_goal_items,
            procedural_skill_items=self.retrieved_procedural_skill_items,
            knowledge_relation_items=self.retrieved_knowledge_relation_items,
            lorebook_items=self.retrieved_lorebook_items,
            entity_state_items=self.retrieved_entity_state_items,
        )
        post_dedup_counts = self._stage_counts(
            short_term_messages=self.post_dedup_short_term_messages,
            core_memories=self.post_dedup_core_memories,
            semantic_memories=self.post_dedup_semantic_memories,
            episodic_memories=self.post_dedup_episodic_memories,
            raw_memories=self.post_dedup_raw_memories,
            goal_items=self.post_dedup_goal_items,
            procedural_skill_items=self.post_dedup_procedural_skill_items,
            knowledge_relation_items=self.post_dedup_knowledge_relation_items,
            lorebook_items=self.post_dedup_lorebook_items,
            entity_state_items=self.post_dedup_entity_state_items,
        )
        final_counts = self._stage_counts(
            short_term_messages=self.short_term_messages,
            core_memories=self.core_memories,
            semantic_memories=self.semantic_memories,
            episodic_memories=self.episodic_memories,
            raw_memories=self.raw_memories,
            goal_items=self.goal_items,
            procedural_skill_items=self.procedural_skill_items,
            knowledge_relation_items=self.knowledge_relation_items,
            lorebook_items=self.lorebook_items,
            entity_state_items=self.entity_state_items,
        )

        budget_report = self.context_budget.to_dict() if self.context_budget else None
        budget_trimmed_items = budget_report.get("trimmed_items", []) if budget_report else []
        over_budget_after_trimming = bool(budget_report.get("over_budget_after_trimming", False)) if budget_report else False

        return [
            {
                "step": "retrieved",
                "label": "Retrieved candidate context",
                "description": "ContextBuilder fetched short-term messages, core memories, and relevant long-term memories before dedup or budget trimming.",
                "status": "ok",
                "counts": retrieved_counts,
                "memory_ids_by_source": self._memory_ids_by_source(
                    self.retrieved_core_memories,
                    self.retrieved_semantic_memories,
                    self.retrieved_episodic_memories,
                    self.retrieved_raw_memories,
                ),
                "goal_ids": self._goal_ids(self.retrieved_goal_items),
                "procedural_skill_ids": self._procedural_skill_ids(self.retrieved_procedural_skill_items),
                "procedural_skill_selection": self.retrieved_procedural_skill_selection,
                "knowledge_relation_ids": self._knowledge_relation_ids(self.retrieved_knowledge_relation_items),
                "lorebook_entry_ids": self._lorebook_entry_ids(self.retrieved_lorebook_items),
                "entity_state_ids": self._entity_state_ids(self.retrieved_entity_state_items),
                "memory_reranking": self.memory_reranking_report(stage="retrieved"),
            },
            {
                "step": "deduped",
                "label": "Applied safe context dedup",
                "description": "Near-duplicate memories were hidden from this prompt only. The database and FAISS index were not modified.",
                "status": "changed" if self.dedup_removed_memories else "ok",
                "input_counts": retrieved_counts,
                "output_counts": post_dedup_counts,
                "removed_count": self.dedup_removed_count(),
                "removed_memory_ids": self.dedup_removed_memory_ids(),
                "removed_details": [item.to_dict() for item in self.dedup_removed_memories],
            },
            {
                "step": "related_relations_expanded",
                "label": "Expanded one-hop knowledge relations",
                "description": "Optional V2 expansion added direct knowledge-relation links touching goals, lorebook entries, entity states, or memories already selected for context.",
                "status": "changed" if self.auto_expanded_knowledge_relation_items else "ok",
                "explicit_knowledge_relation_ids": self.explicit_knowledge_relation_ids(),
                "auto_expanded_knowledge_relation_ids": self.auto_expanded_knowledge_relation_ids(),
                "auto_expanded_count": len(self.auto_expanded_knowledge_relation_items),
                "budget_aware_graph_expansion": self.budget_aware_graph_expansion,
                "counts_after_expansion": post_dedup_counts,
            },
            {
                "step": "budget_trimmed",
                "label": "Applied token budget",
                "description": "The post-dedup context was trimmed if the estimated prompt exceeded the configured budget.",
                "status": (
                    "over_budget"
                    if over_budget_after_trimming
                    else "changed" if budget_trimmed_items
                    else "ok"
                ),
                "input_counts": post_dedup_counts,
                "output_counts": final_counts,
                "budget": budget_report,
            },
            *(
                [
                    {
                        "step": "cognitive_broadcast",
                        "label": "Selected Cognitive Field broadcast",
                        "description": "Optional cognition layer generated candidate thoughts, scored them through resonance/competition, and selected a read-only broadcast focus.",
                        "status": "changed" if self.cognitive_field and self.cognitive_field.winning_thought_id else "ok",
                        "enabled": bool(self.cognitive_field),
                        "winning_thought_id": self.cognitive_field.winning_thought_id if self.cognitive_field else None,
                        "winning_score": self.cognitive_field.winning_score if self.cognitive_field else None,
                        "candidate_count": self.cognitive_field.candidate_count if self.cognitive_field else 0,
                        "broadcast": self.cognitive_field.broadcast.model_dump() if self.cognitive_field else None,
                    }
                ]
                if self.cognitive_field
                else []
            ),
            {
                "step": "final_prompt",
                "label": "Final prompt context",
                "description": "These are the exact context sections that remain in the final prompt sent to the LLM.",
                "status": "over_budget" if over_budget_after_trimming else "ok",
                "counts": final_counts,
                "used_memory_ids": self.used_memory_ids(),
                "used_goal_ids": self.used_goal_ids(),
                "used_procedural_skill_ids": self.used_procedural_skill_ids(),
                "procedural_skill_selection": self.procedural_skill_selection,
                "used_knowledge_relation_ids": self.used_knowledge_relation_ids(),
                "used_lorebook_entry_ids": self.used_lorebook_entry_ids(),
                "used_entity_state_ids": self.used_entity_state_ids(),
                "estimated_prompt_tokens": final_estimated_tokens,
                "prompt_characters": len(final_prompt),
                "memory_reranking": self.memory_reranking_report(stage="final"),
                "cognitive_field": self.cognitive_field.model_dump() if self.cognitive_field else None,
                "perception": self.perception_report.model_dump() if self.perception_report else None,
            "agent_mode": self.agent_mode_profile.model_dump() if self.agent_mode_profile else None,
            "agent_mode_resolution": self.agent_mode_resolution,
                "notes": self._final_prompt_notes(final_counts, over_budget_after_trimming),
            },
        ]

    def _stage_counts(
        self,
        short_term_messages: list[ShortTermMessage],
        core_memories: list[MemoryRecord],
        semantic_memories: list[MemorySearchResult],
        episodic_memories: list[MemorySearchResult],
        raw_memories: list[MemorySearchResult],
        goal_items: list[AgentGoalRead],
        procedural_skill_items: list[AgentProceduralSkillRead],
        knowledge_relation_items: list[KnowledgeRelationRead],
        lorebook_items: list[LorebookContextItem],
        entity_state_items: list[EntityStateRead],
    ) -> dict:
        return {
            "short_term_messages": len(short_term_messages),
            "core_memories": len(core_memories),
            "semantic_memories": len(semantic_memories),
            "episodic_memories": len(episodic_memories),
            "raw_memories": len(raw_memories),
            "goal_items": len(goal_items),
            "procedural_skill_items": len(procedural_skill_items),
            "knowledge_relation_items": len(knowledge_relation_items),
            "lorebook_items": len(lorebook_items),
            "entity_state_items": len(entity_state_items),
            "total_long_term_memories": (
                len(core_memories)
                + len(semantic_memories)
                + len(episodic_memories)
                + len(raw_memories)
            ),
            "total_external_context_items": len(goal_items) + len(procedural_skill_items) + len(knowledge_relation_items) + len(lorebook_items) + len(entity_state_items),
        }

    def _memory_ids_by_source(
        self,
        core_memories: list[MemoryRecord],
        semantic_memories: list[MemorySearchResult],
        episodic_memories: list[MemorySearchResult],
        raw_memories: list[MemorySearchResult],
    ) -> dict:
        return {
            "core": self._memory_ids(core_memories),
            "semantic": self._memory_ids(semantic_memories),
            "episodic": self._memory_ids(episodic_memories),
            "raw": self._memory_ids(raw_memories),
        }

    def _memory_ids(self, memories: list) -> list[int]:
        ids: list[int] = []
        for memory in memories:
            memory_id = getattr(memory, "id", None)
            if memory_id is not None:
                ids.append(int(memory_id))
        return ids

    def _goal_ids(self, items: list[AgentGoalRead]) -> list[int]:
        return [int(item.id) for item in items if item.id is not None]

    def _procedural_skill_ids(self, items: list[AgentProceduralSkillRead]) -> list[int]:
        return [int(item.id) for item in items if item.id is not None]

    def _knowledge_relation_ids(self, items: list[KnowledgeRelationRead]) -> list[int]:
        return [int(item.id) for item in items if item.id is not None]

    def _lorebook_entry_ids(self, items: list[LorebookContextItem]) -> list[int]:
        return [int(item.lorebook_entry_id) for item in items]

    def _entity_state_ids(self, items: list[EntityStateRead]) -> list[int]:
        return [int(item.id) for item in items if item.id is not None]

    def _final_prompt_notes(self, final_counts: dict, over_budget_after_trimming: bool) -> list[str]:
        notes: list[str] = []
        if final_counts.get("total_long_term_memories", 0) == 0:
            notes.append("No long-term memories remain in the final prompt.")
        if final_counts.get("goal_items", 0) == 0:
            notes.append("No goals/plans remain in the final prompt.")
        if final_counts.get("procedural_skill_items", 0) == 0:
            notes.append("No procedural skills remain in the final prompt.")
        if final_counts.get("knowledge_relation_items", 0) == 0:
            notes.append("No knowledge relations remain in the final prompt.")
        if final_counts.get("lorebook_items", 0) == 0:
            notes.append("No lorebook entries remain in the final prompt.")
        if final_counts.get("entity_state_items", 0) == 0:
            notes.append("No entity-state records remain in the final prompt.")
        if over_budget_after_trimming:
            notes.append(
                "The prompt is still over budget after trimming all allowed context items. "
                "This usually means the base prompt, agent profile, user message, or response guidance is too large for the configured budget."
            )
        return notes

    def to_debug_dict(self, include_full_prompt: bool = True, prompt_preview_chars: int = 2000) -> dict:
        """Return a serializable view of the exact context assembled for this turn.

        This is intended for debug UIs/popups. It does not call the LLM.
        """

        full_prompt = self.to_system_prompt()
        safe_preview_chars = max(0, int(prompt_preview_chars))

        return {
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "current_user_message": self.current_user_message,
            "used_memory_ids": self.used_memory_ids(),
            "used_short_term_messages_count": self.used_short_term_count(),
            "used_goal_ids": self.used_goal_ids(),
            "used_goals_count": len(self.goal_items),
            "used_procedural_skill_ids": self.used_procedural_skill_ids(),
            "used_procedural_skills_count": len(self.procedural_skill_items),
            "procedural_skill_selection": self.procedural_skill_selection,
            "used_knowledge_relation_ids": self.used_knowledge_relation_ids(),
            "used_knowledge_relations_count": len(self.knowledge_relation_items),
            "explicit_knowledge_relation_ids": self.explicit_knowledge_relation_ids(),
            "explicit_knowledge_relations_count": len(self.explicit_knowledge_relation_items),
            "auto_expanded_knowledge_relation_ids": self.auto_expanded_knowledge_relation_ids(),
            "auto_expanded_knowledge_relations_count": len(self.auto_expanded_knowledge_relation_items),
            "used_lorebook_entry_ids": self.used_lorebook_entry_ids(),
            "used_lorebook_entries_count": len(self.lorebook_items),
            "used_entity_state_ids": self.used_entity_state_ids(),
            "used_entity_states_count": len(self.entity_state_items),
            "dedup_removed_memories_count": self.dedup_removed_count(),
            "dedup_removed_memory_ids": self.dedup_removed_memory_ids(),
            "dedup_removed_details": [item.to_dict() for item in self.dedup_removed_memories],
            "context_budget": self.context_budget.to_dict() if self.context_budget else None,
            "cognitive_field": self.cognitive_field.model_dump() if self.cognitive_field else None,
            "perception": self.perception_report.model_dump() if self.perception_report else None,
            "agent_mode": self.agent_mode_profile.model_dump() if self.agent_mode_profile else None,
            "agent_mode_resolution": self.agent_mode_resolution,
            "self_model": self.self_model,
            "action_plan": self.action_plan,
            "memory_reranking": self.memory_reranking_report(stage="final"),
            "pipeline_steps": self.pipeline_steps(),
            "sections": {
                "agent_profile": {
                    "name": self.agent_name,
                    "description": self.agent_description,
                    "personality": self.agent_personality,
                    "system_prompt": self.system_prompt,
                },
                "short_term_messages": [
                    {
                        "role": message.role,
                        "content": message.content,
                        "created_at": message.created_at.isoformat(),
                    }
                    for message in self.short_term_messages
                ],
                "core_memories": [self._memory_to_debug_dict(memory, source="core") for memory in self.core_memories],
                "semantic_memories": [self._memory_to_debug_dict(memory, source="semantic") for memory in self.semantic_memories],
                "episodic_memories": [self._memory_to_debug_dict(memory, source="episodic") for memory in self.episodic_memories],
                "raw_memories": [self._memory_to_debug_dict(memory, source="raw") for memory in self.raw_memories],
                "goals": [self._goal_to_debug_dict(item) for item in self.goal_items],
                "procedural_skills": [self._procedural_skill_to_debug_dict(item) for item in self.procedural_skill_items],
                "procedural_skill_selection": self.procedural_skill_selection,
                "knowledge_relations": [self._knowledge_relation_to_debug_dict(item) for item in self.knowledge_relation_items],
                "lorebook": [self._lorebook_to_debug_dict(item) for item in self.lorebook_items],
                "entity_states": [self._entity_state_to_debug_dict(item) for item in self.entity_state_items],
            },
            "prompt_preview": full_prompt[:safe_preview_chars] if safe_preview_chars else "",
            "full_prompt": full_prompt if include_full_prompt else None,
        }

    def memory_reranking_report(self, stage: str = "final") -> list[dict]:
        """Return transparent memory reranking explanations for debug views.

        The reranker stores its explanation in each MemorySearchResult metadata
        under ``_reranking``. This method collects those explanations without
        modifying SQL, FAISS, context lists, or memory access counters.
        """

        from mozok.memory.reranker import explanation_from_memory_metadata

        if stage == "retrieved":
            memories = (
                list(self.retrieved_semantic_memories)
                + list(self.retrieved_episodic_memories)
                + list(self.retrieved_raw_memories)
            )
        else:
            memories = list(self.semantic_memories) + list(self.episodic_memories) + list(self.raw_memories)

        report: list[dict] = []
        seen: set[int] = set()
        for memory in memories:
            memory_id = getattr(memory, "id", None)
            if memory_id is None:
                continue
            memory_id_int = int(memory_id)
            if memory_id_int in seen:
                continue
            explanation = explanation_from_memory_metadata(memory)
            if explanation:
                report.append(explanation)
                seen.add(memory_id_int)
        return report

    def _goal_to_debug_dict(self, item: AgentGoalRead) -> dict:
        return {
            "source": "goal",
            "goal_id": item.id,
            "agent_id": item.agent_id,
            "goal_key": item.goal_key,
            "title": item.title,
            "goal_type": item.goal_type,
            "status": item.status,
            "priority": item.priority,
            "description": item.description,
            "success_criteria": item.success_criteria,
            "failure_conditions": item.failure_conditions,
            "related_entity_ids": item.related_entity_ids,
            "related_lorebook_keys": item.related_lorebook_keys,
            "plan_steps": item.plan_steps,
            "notes": item.notes,
            "metadata": item.metadata,
            "active": item.active,
            "context_line": format_goal_for_prompt_line(item),
        }

    def _procedural_skill_to_debug_dict(self, item: AgentProceduralSkillRead) -> dict:
        return {
            "source": "procedural_skill",
            "procedural_skill_id": item.id,
            "agent_id": item.agent_id,
            "skill_key": item.skill_key,
            "title": item.title,
            "skill_type": item.skill_type,
            "status": item.status,
            "priority": item.priority,
            "description": item.description,
            "trigger": item.trigger,
            "procedure": item.procedure,
            "examples": item.examples,
            "related_goal_keys": item.related_goal_keys,
            "related_entity_ids": item.related_entity_ids,
            "related_lorebook_keys": item.related_lorebook_keys,
            "notes": item.notes,
            "metadata": item.metadata,
            "active": item.active,
            "context_line": format_procedural_skill_for_prompt_line(item),
        }

    def _knowledge_relation_to_debug_dict(self, item: KnowledgeRelationRead) -> dict:
        return {
            "source": "knowledge_relation",
            "knowledge_relation_id": item.id,
            "agent_id": item.agent_id,
            "world_id": item.world_id,
            "source_type": item.source_type,
            "source_id": item.source_id,
            "relation_type": item.relation_type,
            "target_type": item.target_type,
            "target_id": item.target_id,
            "strength": item.strength,
            "confidence": item.confidence,
            "description": item.description,
            "evidence": item.evidence,
            "metadata": item.metadata,
            "active": item.active,
            "origin": "auto_expanded" if item.id in set(self.auto_expanded_knowledge_relation_ids()) else "explicit",
            "context_line": format_knowledge_relation_for_prompt_line(item),
        }

    def _lorebook_to_debug_dict(self, item: LorebookContextItem) -> dict:
        return {
            "source": "lorebook",
            "lorebook_entry_id": item.lorebook_entry_id,
            "world_id": item.world_id,
            "entry_key": item.entry_key,
            "title": item.title,
            "category": item.category,
            "visibility": item.visibility,
            "importance": item.importance,
            "knowledge_state": item.knowledge_state,
            "confidence": item.confidence,
            "content": item.content,
            "tags": item.tags,
            "metadata": item.metadata,
        }

    def _entity_state_to_debug_dict(self, item: EntityStateRead) -> dict:
        return {
            "source": "entity_state",
            "entity_state_id": item.id,
            "agent_id": item.agent_id,
            "entity_id": item.entity_id,
            "entity_name": item.entity_name,
            "entity_type": item.entity_type,
            "role": item.role,
            "state_kind": item.state_kind,
            "attributes": item.attributes,
            "notes": item.notes,
            "metadata": item.metadata,
            "active": item.active,
            "context_line": format_entity_state_for_prompt_line(item),
        }

    def _memory_to_debug_dict(self, memory, source: str) -> dict:
        """Convert a memory object into a JSON-safe debug dictionary.

        Important SQLAlchemy foot-gun:
        Declarative models can expose a `.metadata` attribute from SQLAlchemy
        itself. That object is not JSON serializable and can make FastAPI's
        jsonable_encoder recurse until it crashes.

        Our actual memory metadata lives in `metadata_json` on SQL records and
        in `metadata` on Pydantic search results, so we read those carefully and
        only return plain dictionaries.
        """

        if hasattr(memory, "metadata_json"):
            metadata = getattr(memory, "metadata_json", None)
        else:
            metadata = getattr(memory, "metadata", None)

        if not isinstance(metadata, dict):
            metadata = {}

        return {
            "id": getattr(memory, "id", None),
            "source": source,
            "memory_type": getattr(memory, "memory_type", None),
            "importance": getattr(memory, "importance", None),
            "score": getattr(memory, "score", None),
            "content": getattr(memory, "content", ""),
            "metadata": metadata,
        }

    def to_system_prompt(self) -> str:
        """Convert structured context into a plain system prompt for the LLM."""

        sections: list[str] = []

        if self.system_prompt:
            sections.append(
                "System instructions:\n"
                f"{self.system_prompt}"
            )

        profile_lines = [
            f"Name: {self.agent_name}",
            f"Description: {self.agent_description}",
            f"Personality: {self.agent_personality}",
        ]
        profile_text = "\n".join(line for line in profile_lines if line and not line.endswith(": "))
        if profile_text:
            sections.append(f"Agent profile:\n{profile_text}")

        if self.agent_mode_profile:
            sections.append(self._format_agent_mode_for_prompt())

        if self.goal_items:
            sections.append(
                "Goals / plans currently active for this agent:\n"
                + "\n".join(self._format_goal_for_prompt_line(item) for item in self.goal_items)
            )

        if self.procedural_skill_items:
            sections.append(
                "Procedural skills / behavior strategies available to this agent:\n"
                + "\n".join(self._format_procedural_skill_for_prompt_line(item) for item in self.procedural_skill_items)
            )

        if self.entity_state_items:
            sections.append(
                "Entity state context available to this agent:\n"
                + "\n".join(self._format_entity_state_for_prompt_line(item) for item in self.entity_state_items)
            )

        if self.lorebook_items:
            sections.append(self._format_lorebook_context_for_prompt())

        if self.knowledge_relation_items:
            sections.append(
                "Knowledge relations / links available to this agent:\n"
                + "\n".join(self._format_knowledge_relation_for_prompt_line(item) for item in self.knowledge_relation_items)
            )

        if self.core_memories:
            sections.append(
                "Core/profile memories. Treat these as stable identity or high-priority facts:\n"
                + "\n".join(
                    f"- {self._context_item_text('core', memory, memory.content)}"
                    for memory in self.core_memories
                    if memory.content
                )
            )

        if self.short_term_messages:
            sections.append(
                "Recent conversation / short-term working memory:\n"
                + "\n".join(
                    self._format_short_term_message_for_prompt(message)
                    for message in self.short_term_messages
                    if message.content
                )
            )
        else:
            sections.append("Recent conversation / short-term working memory:\nNo recent messages.")

        if self.semantic_memories:
            sections.append(
                "Relevant semantic memories. These are facts, preferences, summaries, or stable knowledge:\n"
                + "\n".join(
                    f"- {self._context_item_text('semantic', memory, memory.content)}"
                    for memory in self.semantic_memories
                    if memory.content
                )
            )

        if self.episodic_memories:
            sections.append(
                "Relevant episodic memories. These are past events or experiences:\n"
                + "\n".join(
                    f"- {self._context_item_text('episodic', memory, memory.content)}"
                    for memory in self.episodic_memories
                    if memory.content
                )
            )

        if self.raw_memories:
            sections.append(
                "Relevant raw memories. These may be noisy and should be treated carefully:\n"
                + "\n".join(
                    f"- {self._context_item_text('raw', memory, memory.content)}"
                    for memory in self.raw_memories
                    if memory.content
                )
            )

        if self.self_model_prompt_block:
            sections.append(self.self_model_prompt_block)

        if self.action_plan:
            sections.append(self._format_action_plan_for_prompt())

        if self.cognitive_field:
            sections.append(self._format_cognitive_field_for_prompt())

        sections.append(
            "Current user message:\n"
            f"{self.current_user_message}"
        )

        sections.append(
            "Response guidance:\n"
            "- Use memories only when they are relevant.\n"
            "- Do not claim to remember something unless it appears in the provided context.\n"
            "- Goals/plans describe what this agent is currently trying to do. Use them to guide intent, priorities, and next actions without forcing irrelevant behavior.\n"
            "- Procedural skills describe how this agent performs tasks or handles situations. Use them as behavior strategies when they are relevant.\n"
            "- Lorebook/world knowledge is canonical for the selected world and agent access level. "
            "Do not reveal restricted or narrator-only lore unless it appears in the provided lorebook context.\n"
            "- Entity-state context is structured current state about entities from this agent\'s perspective. "
            "Use it only when relevant to the current response.\n"
            "- Knowledge relations are links between memories, goals, lorebook, entity states, and other knowledge nodes. "
            "Use them as supporting structure only when they clarify the current response.\n"
            "- If context conflicts, prefer explicit system instructions, then goals/plans, then procedural skills, then lorebook/world knowledge, "
            "then entity-state context, then knowledge relations, then core/profile memories, then semantic memories, then episodic memories, then raw memories.\n"
            "- Keep the response natural and useful."
        )

        return "\n\n---\n\n".join(section for section in sections if section.strip())


    def _format_agent_mode_for_prompt(self) -> str:
        """Render operating-mode guidance for the LLM.

        Agent mode is not personality. It is the runtime policy for what kind
        of agent is being run: assistant, roleplay character, simulacra NPC,
        narrator, world director, or tool agent.
        """

        if not self.agent_mode_profile:
            return ""

        profile = self.agent_mode_profile
        lines = [
            "Agent operating mode:",
            f"- Mode: {profile.mode} ({profile.label or profile.mode})",
        ]
        if profile.description:
            lines.append(f"- Description: {profile.description}")
        if profile.prompt_guidance:
            lines.append("- Mode guidance:")
            lines.extend(f"  - {item}" for item in profile.prompt_guidance)
        if profile.allowed_entity_state_kinds is not None:
            lines.append("- Allowed entity-state kinds: " + ", ".join(profile.allowed_entity_state_kinds))
        lines.append(f"- Narrator-only lore allowed by this mode: {profile.allow_narrator_only_lore}")
        return "\n".join(lines)

    def _format_action_plan_for_prompt(self) -> str:
        if not self.action_plan:
            return ""
        selected = self.action_plan.get("selected_action") or {}
        lines = ["Action plan / adapter intent for this turn:"]
        if selected:
            lines.append(f"- Selected: {selected.get('label') or selected.get('action_id')} ({selected.get('action_kind')})")
            if selected.get("tool_name"):
                lines.append(f"- Tool: {selected.get('tool_name')}")
            lines.append(f"- Status: {selected.get('status')}; approval_required={selected.get('approval_required')}")
            if selected.get("rationale"):
                lines.append(f"- Rationale: {selected.get('rationale')}")
        policy = self.action_plan.get("execution_policy") or {}
        lines.append(f"- Execution policy: adapter_owned={policy.get('adapter_required', True)}, executes_tools={policy.get('executes_tools', False)}")
        return "\n".join(lines)

    def _format_cognitive_field_for_prompt(self) -> str:
        """Render the optional Cognitive Field broadcast as soft prompt guidance.

        The Cognitive Field is deliberately read-only at this stage. It should
        guide the current response focus, but it must not be treated as a
        permission to create or modify memories, goals, entity states, skills,
        relations, or FAISS entries.
        """

        if not self.cognitive_field:
            return ""

        broadcast = self.cognitive_field.broadcast
        lines = ["Cognitive Field / broadcast focus for this turn:"]

        if broadcast.working_memory_line:
            lines.append(f"- Working focus: {broadcast.working_memory_line}")
        elif broadcast.summary:
            lines.append(f"- Working focus: {broadcast.summary}")

        if broadcast.attention_focus:
            lines.append("- Attention focus: " + ", ".join(str(item) for item in broadcast.attention_focus))

        if broadcast.prompt_guidance:
            lines.append(f"- Prompt guidance: {broadcast.prompt_guidance}")

        if broadcast.update_recommendations:
            lines.append(
                "- Update policy: "
                + " ".join(str(item) for item in broadcast.update_recommendations)
            )
        else:
            lines.append("- Update policy: read-only; do not persist changes from this broadcast alone.")

        return "\n".join(lines)

    def _context_item_text(self, source: str, item, fallback: str) -> str:
        compressed = self.compressed_item_text.get(context_item_key(source, item))
        if compressed is not None:
            return compressed
        return fallback or ""

    def _format_short_term_message_for_prompt(self, message: ShortTermMessage) -> str:
        content = self._context_item_text("short_term", message, self._compact(message.content))
        return f"- {message.role}: {content}"

    def _format_goal_for_prompt_line(self, item: AgentGoalRead) -> str:
        fallback = format_goal_for_prompt_line(item)
        return self._context_item_text("goal", item, fallback)

    def _format_procedural_skill_for_prompt_line(self, item: AgentProceduralSkillRead) -> str:
        fallback = format_procedural_skill_for_prompt_line(item)
        return self._context_item_text("procedural_skill", item, fallback)

    def _format_entity_state_for_prompt_line(self, item: EntityStateRead) -> str:
        fallback = format_entity_state_for_prompt_line(item)
        return self._context_item_text("entity_state", item, fallback)

    def _format_knowledge_relation_for_prompt_line(self, item: KnowledgeRelationRead) -> str:
        fallback = format_knowledge_relation_for_prompt_line(item)
        return self._context_item_text("knowledge_relation", item, fallback)

    def _format_lorebook_context_for_prompt(self) -> str:
        if not self.lorebook_items:
            return "No lorebook entries available for this agent."

        lines = ["Lorebook / world knowledge available to this agent:"]
        for item in self.lorebook_items:
            confidence = f", confidence={item.confidence}/10" if item.confidence is not None else ""
            content = self._context_item_text("lorebook", item, item.content)
            lines.append(
                f"- [{item.category}] {item.title} "
                f"(key={item.entry_key}, state={item.knowledge_state}{confidence}): {content}"
            )
        return "\n".join(lines)

    def _compact(self, text: str, max_chars: int = 700) -> str:
        clean = (text or "").replace("\n", " ").strip()
        if len(clean) <= max_chars:
            return clean
        return clean[: max_chars - 3] + "..."


class ContextBuilder:
    """Builds the context that will be sent to the LLM before each response."""

    def __init__(self, db: Session, memory_service: MemoryService):
        self.db = db
        self.memory_service = memory_service
        self.deduplicator = ContextMemoryDeduplicator()

    def build(
        self,
        agent: AgentRecord,
        user_message: str,
        session_id: str = "default",
        short_term_limit: int = 20,
        core_limit: int = 10,
        semantic_limit: int = 6,
        episodic_limit: int = 4,
        raw_limit: int = 0,
        update_memory_access: bool = True,
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
        sensory_inputs: list[SensoryInput] | None = None,
        perception_events: list[PerceptionEvent] | None = None,
        perception_profile: PerceptionProfile | None = None,
        attention_focus_keywords: list[str] | None = None,
        cognitive_max_candidates: int = 12,
        cognitive_broadcast_top_n: int = 3,
        cognitive_min_score: float = 0.0,
        include_goals: bool = False,
        goal_limit: int = 10,
        goal_status: str | None = None,
        include_procedural_skills: bool = False,
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
        lorebook_limit: int = 0,
        include_public_lore: bool = True,
        include_narrator_only_lore: bool = False,
        include_entity_states: bool = False,
        entity_state_limit: int = 10,
        entity_state_kind: str | None = None,
        entity_state_entity_id: str | None = None,
        agent_mode: str | None = None,
        apply_agent_mode_defaults: bool = True,
        agent_mode_profile_overrides: dict | None = None,
    ) -> ContextPackage:
        """Collect profile + short-term + long-term memory for one LLM turn."""

        agent_id = agent.id
        mode_resolution = AgentModeService().resolve(
            agent,
            agent_mode=agent_mode,
            overrides=agent_mode_profile_overrides or {},
        )
        mode_profile = mode_resolution.profile
        mode_defaults_active = bool(apply_agent_mode_defaults and mode_resolution.source != "default")
        if mode_defaults_active:
            include_narrator_only_lore = bool(include_narrator_only_lore or mode_profile.allow_narrator_only_lore)
            enable_cognitive_field = bool(enable_cognitive_field or mode_profile.enable_cognitive_field_by_default)
            if perception_events and mode_profile.enable_perception_by_default:
                enable_cognitive_field = True

        budget_policy = ContextBudgetPolicy(
            enforce=enforce_token_budget,
            max_prompt_tokens=max_prompt_tokens,
            reserved_response_tokens=reserved_response_tokens,
            allow_core_trimming=allow_core_trimming,
            model_name=token_estimation_model,
            section_budget_tokens=section_budget_tokens or {},
            compression_enabled=compression_enabled,
            short_term_summarization_enabled=short_term_summarization_enabled,
            budget_aware_graph_expansion=budget_aware_graph_expansion,
        )

        short_term_messages = SHORT_TERM_MEMORY.get_messages(
            agent_id=agent_id,
            session_id=session_id,
            limit=short_term_limit,
        )

        core_memories = self._get_core_memories(
            agent_id=agent_id,
            limit=core_limit,
        )

        semantic_memories = self.memory_service.search(
            agent_id=agent_id,
            query=user_message,
            limit=semantic_limit,
            memory_type="semantic",
            update_access=update_memory_access,
        )

        episodic_memories = self.memory_service.search(
            agent_id=agent_id,
            query=user_message,
            limit=episodic_limit,
            memory_type="episodic",
            update_access=update_memory_access,
        )

        raw_memories: list[MemorySearchResult] = []
        if raw_limit > 0:
            raw_memories = self.memory_service.search(
                agent_id=agent_id,
                query=user_message,
                limit=raw_limit,
                memory_type="raw",
                update_access=update_memory_access,
            )

        goal_items: list[AgentGoalRead] = []
        if include_goals and goal_limit > 0:
            goal_records = GoalService(self.db).list_goals(
                agent_id=agent_id,
                status=goal_status,
                include_inactive=False,
                limit=goal_limit,
            )
            goal_items = goal_reads_from_records(goal_records)

        explicit_knowledge_relation_items: list[KnowledgeRelationRead] = []
        if include_knowledge_relations and knowledge_relation_limit > 0:
            knowledge_relation_records = KnowledgeRelationService(self.db).list_relations(
                agent_id=agent_id,
                world_id=knowledge_relation_world_id if knowledge_relation_world_id is not None else world_id,
                source_type=knowledge_relation_source_type,
                source_id=knowledge_relation_source_id,
                target_type=knowledge_relation_target_type,
                target_id=knowledge_relation_target_id,
                relation_type=knowledge_relation_type,
                include_inactive=False,
                limit=knowledge_relation_limit,
            )
            explicit_knowledge_relation_items = knowledge_relation_reads_from_records(knowledge_relation_records)

        lorebook_items: list[LorebookContextItem] = []
        if lorebook_limit > 0:
            lorebook_items = LorebookService(self.db).build_agent_lorebook_context(
                agent_id=agent_id,
                world_id=world_id,
                limit=lorebook_limit,
                include_public=include_public_lore,
                include_narrator_only=include_narrator_only_lore,
            )

        entity_state_items: list[EntityStateRead] = []
        if include_entity_states and entity_state_limit > 0:
            entity_state_records = EntityStateService(self.db).list_states(
                agent_id=agent_id,
                state_kind=entity_state_kind,
                entity_id=entity_state_entity_id,
                include_inactive=False,
                limit=entity_state_limit,
            )
            entity_state_items = reads_from_records(entity_state_records)
            if mode_defaults_active:
                entity_state_items = AgentModeService().filter_entity_states(mode_profile, entity_state_items)


        procedural_skill_items: list[AgentProceduralSkillRead] = []
        procedural_skill_selection: list[dict] = []
        if include_procedural_skills and procedural_skill_limit > 0:
            skill_service = ProceduralSkillService(self.db)
            if select_relevant_procedural_skills:
                selected_skill_records, selection_details = skill_service.select_relevant_skills(
                    agent_id=agent_id,
                    user_message=user_message,
                    skill_type=procedural_skill_type,
                    status=procedural_skill_status,
                    goal_keys=[item.goal_key for item in goal_items],
                    lorebook_keys=[item.entry_key for item in lorebook_items],
                    entity_ids=[item.entity_id for item in entity_state_items],
                    limit=procedural_skill_limit,
                    min_score=procedural_skill_min_score,
                    fallback_to_priority=procedural_skill_fallback_to_priority,
                    include_shared=include_shared_procedural_skills,
                )
                procedural_skill_items = procedural_skill_reads_from_records(selected_skill_records)
                procedural_skill_selection = [item.model_dump() for item in selection_details]
            else:
                procedural_skill_records = skill_service.list_skills(
                    agent_id=agent_id,
                    skill_type=procedural_skill_type,
                    status=procedural_skill_status,
                    include_inactive=False,
                    include_shared=include_shared_procedural_skills,
                    limit=procedural_skill_limit,
                )
                procedural_skill_items = procedural_skill_reads_from_records(procedural_skill_records)

        auto_expanded_knowledge_relation_items: list[KnowledgeRelationRead] = []
        graph_expansion_report: dict = {
            "enabled": bool(budget_policy.budget_aware_graph_expansion),
            "requested_related_limit": int(related_knowledge_relation_limit),
            "effective_related_limit": int(related_knowledge_relation_limit),
            "reason": "not_applied",
        }
        effective_related_knowledge_relation_limit = int(related_knowledge_relation_limit)
        if budget_policy.enforce and budget_policy.budget_aware_graph_expansion:
            effective_related_knowledge_relation_limit = self._budget_aware_related_relation_limit(
                policy=budget_policy,
                requested_limit=related_knowledge_relation_limit,
                explicit_relation_count=len(explicit_knowledge_relation_items),
            )
            graph_expansion_report = {
                "enabled": True,
                "requested_related_limit": int(related_knowledge_relation_limit),
                "effective_related_limit": int(effective_related_knowledge_relation_limit),
                "reason": "capped_by_knowledge_relation_section_budget",
                "section_budget_tokens": budget_policy.section_budget_for("knowledge_relations"),
                "estimated_tokens_per_relation": 28,
                "explicit_relation_count": len(explicit_knowledge_relation_items),
            }

        if include_related_knowledge_relations and effective_related_knowledge_relation_limit > 0:
            node_refs = self._context_node_refs(
                core_memories=core_memories,
                semantic_memories=semantic_memories,
                episodic_memories=episodic_memories,
                raw_memories=raw_memories,
                goal_items=goal_items,
                procedural_skill_items=procedural_skill_items,
                lorebook_items=lorebook_items,
                entity_state_items=entity_state_items,
            )
            explicit_ids = {int(item.id) for item in explicit_knowledge_relation_items if item.id is not None}
            relation_world_id = knowledge_relation_world_id if knowledge_relation_world_id is not None else world_id
            traversal_depth = max(1, min(int(knowledge_relation_traversal_depth), 5))
            if traversal_depth > 1:
                section_budget = budget_policy.section_budget_for("knowledge_relations")
                traversal_token_budget = knowledge_relation_traversal_token_budget
                if traversal_token_budget is None and budget_policy.budget_aware_graph_expansion:
                    traversal_token_budget = section_budget

                graph_response = KnowledgeRelationService(self.db).traverse_graph(
                    agent_id=agent_id,
                    request=KnowledgeRelationGraphDebugRequest(
                        world_id=relation_world_id,
                        roots=[KnowledgeGraphRootNode(node_type=node_type, node_id=node_id) for node_type, node_id in node_refs],
                        direction="both",
                        max_depth=traversal_depth,
                        max_relations=effective_related_knowledge_relation_limit,
                        estimated_token_budget=traversal_token_budget,
                    ),
                )
                auto_expanded_knowledge_relation_items = [
                    item for item in graph_response.relations if int(item.id) not in explicit_ids
                ]
                graph_expansion_report.update(
                    {
                        "mode": "multi_hop_traversal",
                        "traversal_depth": traversal_depth,
                        "graph_node_count": graph_response.node_count,
                        "cycle_count": graph_response.cycle_count,
                        "traversal_report": graph_response.traversal_report,
                    }
                )
            else:
                related_records = KnowledgeRelationService(self.db).list_related_to_nodes(
                    agent_id=agent_id,
                    world_id=relation_world_id,
                    node_refs=node_refs,
                    exclude_ids=explicit_ids,
                    limit=effective_related_knowledge_relation_limit,
                )
                auto_expanded_knowledge_relation_items = knowledge_relation_reads_from_records(related_records)
                graph_expansion_report.update({"mode": "one_hop"})

        knowledge_relation_items = self._merge_knowledge_relation_items(
            explicit_knowledge_relation_items,
            auto_expanded_knowledge_relation_items,
        )

        deduped = self.deduplicator.deduplicate(
            core_memories=core_memories,
            semantic_memories=semantic_memories,
            episodic_memories=episodic_memories,
            raw_memories=raw_memories,
        )

        # Reranking is transient request-time metadata. The search service attaches
        # it to MemorySearchResult objects, and ContextBuilder must make the final
        # prompt order follow that score after safe deduplication has decided which
        # memories survive. This keeps the prompt, debug sections, used_memory_ids,
        # and budget trimming aligned with the same final ordering.
        final_semantic_memories = _sort_memory_search_results_by_reranking_score(
            list(deduped.semantic_memories)
        )
        final_episodic_memories = _sort_memory_search_results_by_reranking_score(
            list(deduped.episodic_memories)
        )
        final_raw_memories = _sort_memory_search_results_by_reranking_score(
            list(deduped.raw_memories)
        )

        context_package = ContextPackage(
            agent_id=agent_id,
            session_id=session_id,
            system_prompt=agent.system_prompt or "",
            agent_name=agent.name or agent.id,
            agent_description=agent.description or "",
            agent_personality=agent.personality or "",
            current_user_message=user_message,
            short_term_messages=short_term_messages,
            core_memories=deduped.core_memories,
            semantic_memories=final_semantic_memories,
            episodic_memories=final_episodic_memories,
            raw_memories=final_raw_memories,
            goal_items=list(goal_items),
            procedural_skill_items=list(procedural_skill_items),
            procedural_skill_selection=list(procedural_skill_selection),
            knowledge_relation_items=list(knowledge_relation_items),
            explicit_knowledge_relation_items=list(explicit_knowledge_relation_items),
            auto_expanded_knowledge_relation_items=list(auto_expanded_knowledge_relation_items),
            lorebook_items=list(lorebook_items),
            entity_state_items=list(entity_state_items),
            dedup_removed_memories=list(deduped.removed),
            budget_aware_graph_expansion=graph_expansion_report,
            retrieved_short_term_messages=list(short_term_messages),
            retrieved_core_memories=list(core_memories),
            retrieved_semantic_memories=list(semantic_memories),
            retrieved_episodic_memories=list(episodic_memories),
            retrieved_raw_memories=list(raw_memories),
            retrieved_goal_items=list(goal_items),
            retrieved_procedural_skill_items=list(procedural_skill_items),
            retrieved_procedural_skill_selection=list(procedural_skill_selection),
            retrieved_knowledge_relation_items=list(knowledge_relation_items),
            retrieved_lorebook_items=list(lorebook_items),
            retrieved_entity_state_items=list(entity_state_items),
            post_dedup_short_term_messages=list(short_term_messages),
            post_dedup_core_memories=list(deduped.core_memories),
            post_dedup_semantic_memories=list(final_semantic_memories),
            post_dedup_episodic_memories=list(final_episodic_memories),
            post_dedup_raw_memories=list(final_raw_memories),
            post_dedup_goal_items=list(goal_items),
            post_dedup_procedural_skill_items=list(procedural_skill_items),
            post_dedup_procedural_skill_selection=list(procedural_skill_selection),
            post_dedup_knowledge_relation_items=list(knowledge_relation_items),
            post_dedup_lorebook_items=list(lorebook_items),
            post_dedup_entity_state_items=list(entity_state_items),
            agent_mode_profile=mode_profile,
            agent_mode_resolution=mode_resolution.model_dump(),
        )

        compiled_sensory_inputs = list(sensory_inputs or [])
        if perception_events:
            perception = PerceptionCompiler().compile(
                events=perception_events or [],
                existing_sensory_inputs=compiled_sensory_inputs,
                profile=perception_profile or PerceptionProfile(),
                message=user_message,
            )
            context_package.perception_report = perception.report
            compiled_sensory_inputs = perception.sensory_inputs

        if enable_cognitive_field:
            context_package.cognitive_field = CognitiveFieldService().run(
                context_package=context_package,
                sensory_inputs=compiled_sensory_inputs,
                attention_focus_keywords=attention_focus_keywords or [],
                max_candidates=cognitive_max_candidates,
                broadcast_top_n=cognitive_broadcast_top_n,
                min_score=cognitive_min_score,
            )

        context_package.context_budget = ContextBudgeter(budget_policy).apply(context_package)

        return context_package


    def _budget_aware_related_relation_limit(
        self,
        policy: ContextBudgetPolicy,
        requested_limit: int,
        explicit_relation_count: int = 0,
    ) -> int:
        safe_requested = max(0, int(requested_limit))
        if safe_requested == 0:
            return 0

        section_budget = policy.section_budget_for("knowledge_relations")
        if section_budget is None:
            return safe_requested

        # Relation prompt lines are usually short, but graph expansion can fan out
        # quickly. Use a conservative fixed estimate before the real prompt exists.
        estimated_tokens_per_relation = 28
        relation_slots = max(0, int(section_budget // estimated_tokens_per_relation))
        auto_slots = max(0, relation_slots - max(0, int(explicit_relation_count)))
        return min(safe_requested, auto_slots)


    def _merge_knowledge_relation_items(
        self,
        explicit_items: list[KnowledgeRelationRead],
        auto_items: list[KnowledgeRelationRead],
    ) -> list[KnowledgeRelationRead]:
        merged: list[KnowledgeRelationRead] = []
        seen: set[int] = set()
        for item in list(explicit_items) + list(auto_items):
            if item.id is None:
                merged.append(item)
                continue
            item_id = int(item.id)
            if item_id not in seen:
                seen.add(item_id)
                merged.append(item)
        return merged

    def _context_node_refs(
        self,
        core_memories: list[MemoryRecord],
        semantic_memories: list[MemorySearchResult],
        episodic_memories: list[MemorySearchResult],
        raw_memories: list[MemorySearchResult],
        goal_items: list[AgentGoalRead],
        procedural_skill_items: list[AgentProceduralSkillRead],
        lorebook_items: list[LorebookContextItem],
        entity_state_items: list[EntityStateRead],
    ) -> list[tuple[str, str]]:
        refs: list[tuple[str, str]] = []

        for memory in list(core_memories) + list(semantic_memories) + list(episodic_memories) + list(raw_memories):
            memory_id = getattr(memory, "id", None)
            if memory_id is not None:
                refs.append(("memory", str(memory_id)))

        for goal in goal_items:
            if getattr(goal, "id", None) is not None:
                refs.append(("goal", str(goal.id)))
            if getattr(goal, "goal_key", None):
                refs.append(("goal", str(goal.goal_key)))

        for skill in procedural_skill_items:
            if getattr(skill, "id", None) is not None:
                refs.append(("procedural_skill", str(skill.id)))
            if getattr(skill, "skill_key", None):
                refs.append(("procedural_skill", str(skill.skill_key)))
                refs.append(("skill", str(skill.skill_key)))

        for item in lorebook_items:
            if getattr(item, "lorebook_entry_id", None) is not None:
                refs.append(("lorebook", str(item.lorebook_entry_id)))
            if getattr(item, "entry_key", None):
                refs.append(("lorebook", str(item.entry_key)))

        for state in entity_state_items:
            if getattr(state, "id", None) is not None:
                refs.append(("entity_state", str(state.id)))
            if getattr(state, "entity_id", None):
                refs.append(("entity_state", str(state.entity_id)))

        seen: set[tuple[str, str]] = set()
        unique: list[tuple[str, str]] = []
        for node_type, node_id in refs:
            key = (node_type, node_id)
            if node_id and key not in seen:
                seen.add(key)
                unique.append(key)
        return unique

    def _get_core_memories(self, agent_id: str, limit: int) -> list[MemoryRecord]:
        """Core memories are usually always relevant, so fetch them directly from SQL."""

        safe_limit = max(0, int(limit))
        if safe_limit == 0:
            return []

        return (
            self.db.query(MemoryRecord)
            .filter(
                MemoryRecord.agent_id == agent_id,
                MemoryRecord.active == True,  # noqa: E712
                MemoryRecord.memory_type == MEMORY_LEVEL_CORE,
            )
            .order_by(MemoryRecord.importance.desc(), MemoryRecord.created_at.desc())
            .limit(safe_limit)
            .all()
        )