from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from sqlalchemy import and_, or_

from sqlalchemy.orm import Session

from mozok.db.models import AgentRecord, MemoryRecord
from mozok.knowledge_relations.models import KnowledgeRelationRecord
from mozok.embeddings.base import EmbeddingService
from mozok.faiss_index.store import FaissMemoryIndex
from mozok.llm.ollama_openai import OllamaOpenAIClient
from mozok.memory.policy import (
    FORGET_ACTION_ARCHIVE,
    FORGET_ACTION_DECAY,
    FORGET_ACTION_HARD_DELETE,
    FORGET_ACTION_PROTECT,
    FORGET_ACTION_SOFT_DELETE,
    FORGET_ACTION_SUMMARIZE,
    FORGET_ACTION_SUMMARIZE_THEN_ARCHIVE,
    MEMORY_LEVEL_CORE,
    MEMORY_LEVEL_EPISODIC,
    MEMORY_LEVEL_RAW,
    MEMORY_LEVEL_SEMANTIC,
    coerce_memory_policy,
    deep_merge_dicts,
    fresh_default_memory_policy,
    normalize_memory_type,
    search_aliases_for_memory_type,
)
from mozok.memory.summarizer import (
    MemorySummarizer,
    estimate_summary_emotional_weight,
    estimate_summary_importance,
)
from mozok.memory.reranker import MemoryRelationSignal, MemoryReranker, MemoryRerankingContext
from mozok.schemas.memory import MemoryCreate, MemoryMaintenanceResponse, MemorySearchResult


class MemoryService:
    """The only public doorway to bot memory.

    This class deliberately hides the SQL + FAISS split from the rest of the app.
    Other modules should not manually write memories to SQL or FAISS.

    Mozok's current memory model has four broad levels:
    - raw: fresh dialogue and noisy observations;
    - episodic: meaningful events and experiences;
    - semantic: facts, preferences, stable knowledge and summaries;
    - core: identity/profile/personality/critical relationship memory.

    The forgetting/maintenance policy is stored per agent in:
    agent.metadata_json["memory_policy"]
    """

    def __init__(
        self,
        db: Session,
        embedding_service: EmbeddingService,
        vector_index: FaissMemoryIndex,
    ):
        self.db = db
        self.embedding_service = embedding_service
        self.vector_index = vector_index
        self.summarizer = MemorySummarizer(llm_client=OllamaOpenAIClient())

    # ---------------------------------------------------------------------
    # Agent policy helpers
    # ---------------------------------------------------------------------

    def _utc_now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _ensure_agent(self, agent_id: str) -> AgentRecord:
        """Ensure memory endpoints can work even before /chat creates an agent."""

        agent = self.db.get(AgentRecord, agent_id)
        if agent is not None:
            return agent

        agent = AgentRecord(
            id=agent_id,
            name=agent_id,
            description="Default Mozok agent.",
            personality="Helpful, curious, and remembers relevant past events.",
            system_prompt="Use memories when relevant. Do not invent memories.",
            state_json={},
            metadata_json={
                "memory_policy": fresh_default_memory_policy(),
                "memory_maintenance": {},
            },
        )
        self.db.add(agent)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def get_memory_policy(self, agent_id: str) -> dict[str, Any]:
        """Return the complete memory policy for an agent, including defaults."""

        agent = self._ensure_agent(agent_id)
        metadata = dict(agent.metadata_json or {})
        policy = coerce_memory_policy(metadata.get("memory_policy"))

        # Save the completed policy back once, so users can see all settings in /memory-policy.
        metadata["memory_policy"] = policy
        metadata.setdefault("memory_maintenance", {})
        agent.metadata_json = metadata
        agent.updated_at = self._utc_now()
        self.db.commit()

        return policy

    def update_memory_policy(self, agent_id: str, partial_policy: dict[str, Any]) -> dict[str, Any]:
        """Merge a partial policy update into the agent policy.

        This gives lightweight control over which triggers are enabled and what N means.
        """

        agent = self._ensure_agent(agent_id)
        metadata = dict(agent.metadata_json or {})
        current_policy = coerce_memory_policy(metadata.get("memory_policy"))
        updated_policy = coerce_memory_policy(deep_merge_dicts(current_policy, partial_policy or {}))

        metadata["memory_policy"] = updated_policy
        metadata.setdefault("memory_maintenance", {})
        agent.metadata_json = metadata
        agent.updated_at = self._utc_now()
        self.db.commit()

        return updated_policy

    def _maintenance_state(self, agent: AgentRecord) -> dict[str, Any]:
        metadata = dict(agent.metadata_json or {})
        state = dict(metadata.get("memory_maintenance") or {})
        return state

    def _save_maintenance_state(self, agent: AgentRecord, state: dict[str, Any]) -> None:
        metadata = dict(agent.metadata_json or {})
        metadata["memory_maintenance"] = state
        agent.metadata_json = metadata
        agent.updated_at = self._utc_now()
        self.db.commit()

    # ---------------------------------------------------------------------
    # Add/search memory
    # ---------------------------------------------------------------------

    def add_memory(self, data: MemoryCreate) -> MemoryRecord:
        """Save memory in SQL, index it in FAISS, then check maintenance triggers.

        Current simplification:
        - If FAISS indexing fails after SQL commit, index can be rebuilt later.
        - Production version should use pending-index jobs.
        """

        normalized_memory_type = normalize_memory_type(data.memory_type)
        metadata = dict(data.metadata or {})
        metadata.setdefault("memory_level", normalized_memory_type)

        if data.session_id:
            metadata.setdefault("session_id", data.session_id)

        record = self._create_memory_record(
            agent_id=data.agent_id,
            content=data.content,
            memory_type=normalized_memory_type,
            importance=data.importance,
            emotional_weight=data.emotional_weight,
            metadata=metadata,
            index=True,
        )

        if not metadata.get("maintenance_generated"):
            self._handle_maintenance_triggers_after_add(record)

        return record

    def _create_memory_record(
        self,
        agent_id: str,
        content: str,
        memory_type: str,
        importance: int,
        emotional_weight: float,
        metadata: dict[str, Any] | None = None,
        index: bool = True,
    ) -> MemoryRecord:
        self._ensure_agent(agent_id)

        record = MemoryRecord(
            agent_id=agent_id,
            memory_type=normalize_memory_type(memory_type),
            content=content,
            importance=max(1, min(10, int(importance))),
            emotional_weight=float(emotional_weight),
            metadata_json=metadata or {},
        )

        self.db.add(record)
        self.db.commit()
        self.db.refresh(record)

        if index:
            vector = self.embedding_service.embed_text(content)
            self.vector_index.add(record.id, vector)

        return record

    def search(
            self,
            agent_id: str,
            query: str,
            limit: int = 5,
            memory_type: str | None = None,
            update_access: bool = True,
    ) -> list[MemorySearchResult]:
        """Semantic search.

        FAISS returns candidate IDs.
        SQL validates/filter/sorts them.
        This means FAISS is fast, while SQL remains the source of truth.
        """

        query_vector = self.embedding_service.embed_text(query)

        # Ask FAISS for more than we need because SQL filters may remove some.
        candidate_count = max(limit * 10, 25)
        candidates = self.vector_index.search(query_vector, limit=candidate_count)
        if not candidates:
            return []

        score_by_id = {memory_id: score for memory_id, score in candidates}
        ids = list(score_by_id.keys())

        query_obj = self.db.query(MemoryRecord).filter(
            MemoryRecord.id.in_(ids),
            MemoryRecord.agent_id == agent_id,
            MemoryRecord.active == True,  # noqa: E712 - SQLAlchemy syntax
        )

        if memory_type is not None:
            query_obj = query_obj.filter(MemoryRecord.memory_type.in_(search_aliases_for_memory_type(memory_type)))

        records = query_obj.all()

        # Patch 26.4: transparent deterministic reranking for live search results.
        # The SQL records are not mutated with debug data; reranking explanations
        # are attached only to the outgoing MemorySearchResult.metadata.
        relation_signals = self._memory_relation_signals_for_reranking(
            agent_id=agent_id,
            memory_ids=[int(record.id) for record in records],
        )
        reranked_items = MemoryReranker().rerank(
            records,
            vector_scores=score_by_id,
            context=MemoryRerankingContext(
                now=self._utc_now(),
                relation_signals=relation_signals,
            ),
            limit=limit,
        )
        ranked = [item.record for item in reranked_items]
        reranking_by_id = {
            int(item.record.id): item.explanation.to_dict()
            for item in reranked_items
        }

        if update_access and ranked:
            now = self._utc_now()
            for record in ranked:
                metadata = dict(record.metadata_json or {})
                metadata["access_count"] = int(metadata.get("access_count", 0)) + 1
                record.metadata_json = metadata
                record.last_accessed_at = now
            self.db.commit()

        results: list[MemorySearchResult] = []
        for record in ranked:
            metadata = dict(record.metadata_json or {})
            explanation = reranking_by_id.get(int(record.id))
            if explanation is not None:
                metadata["_reranking"] = explanation
            results.append(
                MemorySearchResult(
                    id=record.id,
                    content=record.content,
                    memory_type=record.memory_type,
                    importance=record.importance,
                    score=score_by_id.get(record.id, 0.0),
                    metadata=metadata,
                )
            )
        return results


    def _memory_relation_signals_for_reranking(
        self,
        *,
        agent_id: str,
        memory_ids: list[int],
    ) -> dict[int, MemoryRelationSignal]:
        """Return graph signals for memories without changing SQL or FAISS."""

        if not memory_ids:
            return {}

        memory_id_strings = [str(memory_id) for memory_id in memory_ids]
        signals: dict[int, MemoryRelationSignal] = {
            int(memory_id): MemoryRelationSignal() for memory_id in memory_ids
        }

        try:
            relations = (
                self.db.query(KnowledgeRelationRecord)
                .filter(
                    KnowledgeRelationRecord.agent_id == agent_id,
                    KnowledgeRelationRecord.active == True,  # noqa: E712 - SQLAlchemy syntax
                    or_(
                        and_(
                            KnowledgeRelationRecord.source_type == "memory",
                            KnowledgeRelationRecord.source_id.in_(memory_id_strings),
                        ),
                        and_(
                            KnowledgeRelationRecord.target_type == "memory",
                            KnowledgeRelationRecord.target_id.in_(memory_id_strings),
                        ),
                    ),
                )
                .all()
            )
        except Exception:
            # Some tests or lightweight deployments may not have the relation
            # table available yet. Reranking must degrade gracefully.
            return signals

        for relation in relations:
            try:
                if relation.source_type == "memory":
                    memory_id = int(relation.source_id)
                    other_type = str(relation.target_type or "")
                else:
                    memory_id = int(relation.target_id)
                    other_type = str(relation.source_type or "")
            except (TypeError, ValueError):
                continue

            signal = signals.setdefault(memory_id, MemoryRelationSignal())
            signal.relation_count += 1
            signal.max_strength = max(signal.max_strength, float(relation.strength or 0.0))
            signal.max_confidence = max(signal.max_confidence, float(relation.confidence or 0.0))
            if relation.relation_type:
                signal.relation_types.append(str(relation.relation_type))

            normalised_other_type = other_type.lower()
            if normalised_other_type in {"goal", "agent_goal", "plan_step"}:
                signal.active_goal_count += 1
            elif normalised_other_type in {"lorebook", "lorebook_entry", "lore"}:
                signal.lorebook_count += 1
            elif normalised_other_type in {"entity_state", "entity", "faction", "quest", "location", "object"}:
                signal.entity_state_count += 1

        return signals

    # ---------------------------------------------------------------------
    # Forget actions
    # ---------------------------------------------------------------------

    def soft_delete(self, memory_id: int, reason: str = "manual") -> bool:
        """Deactivate a memory in SQL.

        FAISS may still contain the vector, but search() filters inactive records out.
        This is intentional; periodic rebuild_index() removes dead vectors.
        """

        record = self.db.get(MemoryRecord, memory_id)
        if record is None:
            return False

        self._archive_or_deactivate_record(record, action=FORGET_ACTION_SOFT_DELETE, reason=reason)
        self.db.commit()
        return True

    def forget_memory(
        self,
        memory_id: int,
        action: str,
        reason: str = "manual",
        decay_amount: int = 1,
        rebuild_index: bool = True,
    ) -> dict[str, Any]:
        """Apply an explicit forget action to one memory.

        This is intentionally broader than delete:
        - decay: lower importance;
        - archive: remove from active search but keep SQL record;
        - summarize: create a semantic summary of the memory;
        - summarize_then_archive: summarize and then archive original;
        - soft_delete: deactivate original;
        - hard_delete: physically remove SQL record;
        - protect: mark the memory as protected.
        """

        record = self.db.get(MemoryRecord, memory_id)
        if record is None:
            return {
                "memory_id": memory_id,
                "action": action,
                "changed": False,
                "message": "Memory not found.",
            }

        normalized_action = (action or FORGET_ACTION_ARCHIVE).strip().lower()
        if normalized_action == FORGET_ACTION_DECAY:
            self._decay_record(record, decay_amount=decay_amount, reason=reason)
            message = "Memory importance decayed."
        elif normalized_action == FORGET_ACTION_ARCHIVE:
            self._archive_or_deactivate_record(record, action=FORGET_ACTION_ARCHIVE, reason=reason)
            message = "Memory archived. It remains in SQL but is no longer active in search."
        elif normalized_action == FORGET_ACTION_SUMMARIZE:
            summary = self._create_summary_memory(record.agent_id, [record], trigger=reason)
            message = f"Created semantic summary memory {summary.id}. Original remains active."
        elif normalized_action == FORGET_ACTION_SUMMARIZE_THEN_ARCHIVE:
            summary = self._create_summary_memory(record.agent_id, [record], trigger=reason)
            self._archive_or_deactivate_record(record, action=FORGET_ACTION_ARCHIVE, reason=reason)
            message = f"Created semantic summary memory {summary.id}; original archived."
        elif normalized_action == FORGET_ACTION_SOFT_DELETE:
            self._archive_or_deactivate_record(record, action=FORGET_ACTION_SOFT_DELETE, reason=reason)
            message = "Memory soft-deleted."
        elif normalized_action == FORGET_ACTION_HARD_DELETE:
            self.db.delete(record)
            message = "Memory hard-deleted from SQL."
        elif normalized_action == FORGET_ACTION_PROTECT:
            self._protect_record(record, reason=reason)
            message = "Memory protected from automatic maintenance."
        else:
            return {
                "memory_id": memory_id,
                "action": action,
                "changed": False,
                "message": f"Unknown forget action: {action}",
            }

        self.db.commit()
        if rebuild_index and normalized_action in {
            FORGET_ACTION_ARCHIVE,
            FORGET_ACTION_SOFT_DELETE,
            FORGET_ACTION_HARD_DELETE,
            FORGET_ACTION_SUMMARIZE_THEN_ARCHIVE,
        }:
            self.rebuild_index()

        return {
            "memory_id": memory_id,
            "action": normalized_action,
            "changed": True,
            "message": message,
        }

    # ---------------------------------------------------------------------
    # Maintenance / sleep cycle
    # ---------------------------------------------------------------------

    def _handle_maintenance_triggers_after_add(self, record: MemoryRecord) -> None:
        """Check the four automatic add-time triggers.

        after_session is intentionally not handled here because only the adapter
        knows when a session truly ends.
        """

        agent = self._ensure_agent(record.agent_id)
        policy = self.get_memory_policy(record.agent_id)
        triggers = policy.get("triggers", {})
        state = self._maintenance_state(agent)

        state["memories_since_maintenance"] = int(state.get("memories_since_maintenance", 0)) + 1
        self._save_maintenance_state(agent, state)

        reasons: list[str] = []

        every_n = triggers.get("every_n_memories", {})
        every_n_value = max(1, int(every_n.get("n", 100)))
        if every_n.get("enabled", True) and state["memories_since_maintenance"] >= every_n_value:
            reasons.append("every_n_memories")

        memory_limit = triggers.get("memory_limit", {})
        if memory_limit.get("enabled", True):
            max_active = max(1, int(memory_limit.get("max_active_memories", 2000)))
            active_count = self._active_memory_count(record.agent_id)
            if active_count > max_active:
                reasons.append("memory_limit")

        time_interval = triggers.get("time_interval", {})
        if time_interval.get("enabled", False):
            hours = max(1, int(time_interval.get("hours", 24)))
            last_at = self._parse_dt(state.get("last_maintenance_at"))
            if last_at is None or self._utc_now() - last_at >= timedelta(hours=hours):
                reasons.append("time_interval")

        important_event = triggers.get("important_event", {})
        if important_event.get("enabled", True):
            min_importance = int(important_event.get("min_importance", 8))
            min_abs_emotional_weight = float(important_event.get("min_abs_emotional_weight", 0.75))
            if record.importance >= min_importance or abs(record.emotional_weight) >= min_abs_emotional_weight:
                self._protect_record(record, reason="important_event")
                reasons.append("important_event")
                self.db.commit()

        # If multiple triggers fired, one maintenance pass is enough.
        if reasons:
            self.run_maintenance(agent_id=record.agent_id, trigger="+".join(reasons), rebuild_index=True)

    def run_maintenance(
        self,
        agent_id: str,
        trigger: str = "manual",
        rebuild_index: bool = True,
    ) -> MemoryMaintenanceResponse:
        """Run a configurable memory sleep/consolidation pass.

        The pass is conservative by design:
        - core/profile memories are protected;
        - high-importance memories are protected;
        - raw memories are summarized before being archived;
        - automatic hard-delete is disabled unless the policy explicitly allows it.
        """

        agent = self._ensure_agent(agent_id)
        policy = self.get_memory_policy(agent_id)
        rules = policy.get("rules", {})
        trigger_parts = {part.strip() for part in trigger.split("+") if part.strip()}
        now = self._utc_now()

        checked_records = self.db.query(MemoryRecord).filter(
            MemoryRecord.agent_id == agent_id,
            MemoryRecord.active == True,  # noqa: E712
        ).all()

        checked_count = len(checked_records)
        summarized_count = 0
        decayed_count = 0
        archived_count = 0
        protected_count = 0
        deleted_count = 0
        created_summary_ids: list[int] = []
        notes: list[str] = []

        protect_importance = int(rules.get("protect_importance_at_or_above", 8))
        raw_ttl_days = int(rules.get("raw_ttl_days", 7))
        episodic_decay_after_days = int(rules.get("episodic_decay_after_days", 30))
        summary_min_source = int(rules.get("summary_min_source_memories", 4))
        summary_max_source = int(rules.get("summary_max_source_memories", 40))
        max_raw_before_summary = int(rules.get("max_raw_memories_before_summary", 100))
        decay_amount = int(rules.get("decay_amount", 1))
        archive_score_below = float(rules.get("archive_retention_score_below", 0.20))
        allow_automatic_hard_delete = bool(rules.get("allow_automatic_hard_delete", False))

        # 1) Protect core/profile and high-importance memories.
        for record in checked_records:
            if self._is_protected(record, protect_importance):
                if not self._metadata(record).get("protected"):
                    self._protect_record(record, reason="maintenance_protection")
                    protected_count += 1

        # 2) Raw memory consolidation.
        raw_candidates = [
            record
            for record in checked_records
            if record.memory_type == MEMORY_LEVEL_RAW and not self._is_protected(record, protect_importance)
        ]
        raw_candidates.sort(key=lambda r: r.created_at or now)

        expired_raw = [
            record
            for record in raw_candidates
            if self._age_days(record, now) >= raw_ttl_days
        ]

        # Every-N/session/time triggers can summarize recent raw memory even if it is not old yet.
        should_consolidate_raw = bool(
            trigger_parts.intersection({"every_n_memories", "after_session", "time_interval", "manual"})
            or len(raw_candidates) >= max_raw_before_summary
        )

        raw_to_summarize = expired_raw
        if should_consolidate_raw and len(raw_candidates) >= summary_min_source:
            raw_to_summarize = raw_candidates[:summary_max_source]

        if len(raw_to_summarize) >= summary_min_source:
            summary = self._create_summary_memory(agent_id, raw_to_summarize[:summary_max_source], trigger=trigger)
            created_summary_ids.append(summary.id)
            summarized_count += len(raw_to_summarize[:summary_max_source])
            for record in raw_to_summarize[:summary_max_source]:
                self._archive_or_deactivate_record(record, action=FORGET_ACTION_ARCHIVE, reason=f"maintenance:{trigger}")
                archived_count += 1
        elif expired_raw:
            # If there are too few raw memories to summarize use simple archive.
            for record in expired_raw:
                self._archive_or_deactivate_record(record, action=FORGET_ACTION_ARCHIVE, reason=f"maintenance:{trigger}:expired_raw")
                archived_count += 1

        # 3) Episodic decay. Important episodes stay protected.
        for record in checked_records:
            if record.memory_type != MEMORY_LEVEL_EPISODIC:
                continue
            if self._is_protected(record, protect_importance):
                continue
            if self._age_days(record, now) >= episodic_decay_after_days:
                before = record.importance
                self._decay_record(record, decay_amount=decay_amount, reason=f"maintenance:{trigger}:stale_episodic")
                if record.importance != before:
                    decayed_count += 1

        # 4) Low retention score archiving.
        for record in checked_records:
            if not record.active:
                continue
            if record.memory_type in {MEMORY_LEVEL_CORE, MEMORY_LEVEL_SEMANTIC}:
                continue
            if self._is_protected(record, protect_importance):
                continue
            score = self._retention_score(record, now)
            if score < archive_score_below:
                self._archive_or_deactivate_record(record, action=FORGET_ACTION_ARCHIVE, reason=f"maintenance:{trigger}:low_score")
                archived_count += 1

        # 5) Memory limit pressure: archive weakest non-core memories until under limit.
        memory_limit = policy.get("triggers", {}).get("memory_limit", {})
        if memory_limit.get("enabled", True):
            max_active = max(1, int(memory_limit.get("max_active_memories", 2000)))
            active_records = self.db.query(MemoryRecord).filter(
                MemoryRecord.agent_id == agent_id,
                MemoryRecord.active == True,  # noqa: E712
            ).all()
            overflow = len(active_records) - max_active
            if overflow > 0:
                pressure_candidates = [
                    record
                    for record in active_records
                    if record.memory_type != MEMORY_LEVEL_CORE and not self._is_protected(record, protect_importance)
                ]
                pressure_candidates.sort(key=lambda r: self._retention_score(r, now))

                for record in pressure_candidates[:overflow]:
                    if allow_automatic_hard_delete:
                        self.db.delete(record)
                        deleted_count += 1
                    else:
                        self._archive_or_deactivate_record(record, action=FORGET_ACTION_ARCHIVE, reason=f"maintenance:{trigger}:memory_limit")
                        archived_count += 1

                notes.append(f"Memory limit pressure: overflow={overflow}, handled={min(overflow, len(pressure_candidates))}.")

        # Save agent maintenance state.
        state = self._maintenance_state(agent)
        state["memories_since_maintenance"] = 0
        state["last_maintenance_at"] = now.isoformat()
        state["last_maintenance_trigger"] = trigger
        self._save_maintenance_state(agent, state)

        self.db.commit()

        indexed_count: int | None = None
        rebuilt = False
        if rebuild_index:
            indexed_count = self.rebuild_index()
            rebuilt = True

        if not created_summary_ids and not archived_count and not decayed_count and not protected_count and not deleted_count:
            notes.append("Nothing needed changing under the current policy.")

        return MemoryMaintenanceResponse(
            agent_id=agent_id,
            trigger=trigger,
            checked_memories=checked_count,
            summarized_memories=summarized_count,
            decayed_memories=decayed_count,
            archived_memories=archived_count,
            protected_memories=protected_count,
            deleted_memories=deleted_count,
            created_summary_ids=created_summary_ids,
            rebuilt_index=rebuilt,
            indexed_memories=indexed_count,
            notes=notes,
        )

    def end_session(self, agent_id: str, rebuild_index: bool = True) -> MemoryMaintenanceResponse:
        """Convenience wrapper for the 'after each session' trigger."""

        policy = self.get_memory_policy(agent_id)
        after_session = policy.get("triggers", {}).get("after_session", {})
        if not after_session.get("enabled", True):
            return MemoryMaintenanceResponse(
                agent_id=agent_id,
                trigger="after_session",
                checked_memories=0,
                summarized_memories=0,
                decayed_memories=0,
                archived_memories=0,
                protected_memories=0,
                deleted_memories=0,
                created_summary_ids=[],
                rebuilt_index=False,
                indexed_memories=None,
                notes=["after_session trigger is disabled for this agent."],
            )
        return self.run_maintenance(agent_id=agent_id, trigger="after_session", rebuild_index=rebuild_index)

    # ---------------------------------------------------------------------
    # FAISS rebuild
    # ---------------------------------------------------------------------

    def rebuild_index(self) -> int:
        """Rebuild FAISS from active SQL memories.

        This is the safety valve that makes SQL + FAISS manageable.
        """

        records = self.db.query(MemoryRecord).filter(MemoryRecord.active == True).all()  # noqa: E712
        if not records:
            # Keep FAISS empty if there are no active memories.
            # We cannot know the embedding dimension without embedding something,
            # so reset lazily on the next added memory.
            self.vector_index.clear()
            return 0

        first_vector = self.embedding_service.embed_text(records[0].content)
        self.vector_index.reset(dim=first_vector.shape[0])
        self.vector_index.add(records[0].id, first_vector)

        for record in records[1:]:
            vector = self.embedding_service.embed_text(record.content)
            self.vector_index.add(record.id, vector)

        return len(records)

    # ---------------------------------------------------------------------
    # Internal mechanics
    # ---------------------------------------------------------------------

    def _active_memory_count(self, agent_id: str) -> int:
        return self.db.query(MemoryRecord).filter(
            MemoryRecord.agent_id == agent_id,
            MemoryRecord.active == True,  # noqa: E712
        ).count()

    def _metadata(self, record: MemoryRecord) -> dict[str, Any]:
        return dict(record.metadata_json or {})

    def _access_count(self, record: MemoryRecord) -> int:
        return int(self._metadata(record).get("access_count", 0))

    def _is_protected(self, record: MemoryRecord, protect_importance: int) -> bool:
        metadata = self._metadata(record)
        return (
            record.memory_type == MEMORY_LEVEL_CORE
            or bool(metadata.get("protected"))
            or record.importance >= protect_importance
        )

    def _protect_record(self, record: MemoryRecord, reason: str) -> None:
        metadata = self._metadata(record)
        metadata["protected"] = True
        metadata["protected_reason"] = reason
        metadata["protected_at"] = self._utc_now().isoformat()
        record.metadata_json = metadata
        record.updated_at = self._utc_now()

    def _decay_record(self, record: MemoryRecord, decay_amount: int, reason: str) -> None:
        metadata = self._metadata(record)
        metadata.setdefault("forget_history", [])
        metadata["forget_history"].append(
            {
                "action": FORGET_ACTION_DECAY,
                "reason": reason,
                "at": self._utc_now().isoformat(),
                "old_importance": record.importance,
                "decay_amount": decay_amount,
            }
        )
        record.importance = max(1, record.importance - max(1, int(decay_amount)))
        metadata["last_forget_action"] = FORGET_ACTION_DECAY
        metadata["last_forget_reason"] = reason
        record.metadata_json = metadata
        record.updated_at = self._utc_now()

    def _archive_or_deactivate_record(self, record: MemoryRecord, action: str, reason: str) -> None:
        metadata = self._metadata(record)
        metadata.setdefault("forget_history", [])
        metadata["forget_history"].append(
            {
                "action": action,
                "reason": reason,
                "at": self._utc_now().isoformat(),
            }
        )
        metadata["archived"] = True
        metadata["last_forget_action"] = action
        metadata["last_forget_reason"] = reason
        metadata["archived_at"] = self._utc_now().isoformat()
        record.metadata_json = metadata
        record.active = False
        record.updated_at = self._utc_now()

    def _create_summary_memory(
        self,
        agent_id: str,
        source_records: list[MemoryRecord],
        trigger: str,
    ) -> MemoryRecord:
        """Create a semantic summary memory.

        First tries the configured LLM summarizer. If Ollama/model access fails,
        MemorySummarizer returns a deterministic fallback so maintenance still
        completes and the bot does not lose data.
        """

        now = self._utc_now()
        source_records = [record for record in source_records if record is not None]
        source_ids = [record.id for record in source_records]
        policy = self.get_memory_policy(agent_id)

        summary = self.summarizer.summarize(
            agent_id=agent_id,
            source_records=source_records,
            trigger=trigger,
            policy=policy,
        )

        content = summary.content.strip()
        if not content:
            # Last-resort safety net: never create an empty memory.
            content = self.summarizer.deterministic_summary(
                agent_id=agent_id,
                source_records=source_records,
                trigger=trigger,
            )

        metadata = {
            "maintenance_generated": True,
            "summary_kind": "maintenance_consolidation",
            "source_memory_ids": source_ids,
            "source_memory_count": len(source_records),
            "trigger": trigger,
            "created_at": now.isoformat(),
            "summary_method": summary.method,
        }
        if summary.model:
            metadata["summary_model"] = summary.model
        if summary.error:
            metadata["summary_error"] = summary.error

        return self._create_memory_record(
            agent_id=agent_id,
            content=content,
            memory_type=MEMORY_LEVEL_SEMANTIC,
            importance=estimate_summary_importance(source_records),
            emotional_weight=estimate_summary_emotional_weight(source_records),
            metadata=metadata,
            index=True,
        )

    def _age_days(self, record: MemoryRecord, now: datetime | None = None) -> float:
        now = now or self._utc_now()
        created_at = record.created_at or now
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        return max(0.0, (now - created_at).total_seconds() / 86400.0)

    def _retention_score(self, record: MemoryRecord, now: datetime | None = None) -> float:
        """A small, explainable score used by maintenance.

        Rough intuition:
        - importance and emotional weight keep memories alive;
        - repeated access keeps memories alive;
        - age slowly lowers the score;
        - raw memories decay faster than semantic/core memories.
        """

        now = now or self._utc_now()
        age_days = self._age_days(record, now)
        access_count = min(self._access_count(record), 20)

        base = record.importance / 10.0
        emotion_bonus = min(abs(record.emotional_weight), 1.0) * 0.20
        access_bonus = access_count * 0.02

        if record.memory_type == MEMORY_LEVEL_RAW:
            age_penalty = age_days * 0.08
        elif record.memory_type == MEMORY_LEVEL_EPISODIC:
            age_penalty = age_days * 0.02
        elif record.memory_type == MEMORY_LEVEL_SEMANTIC:
            age_penalty = age_days * 0.005
        else:
            age_penalty = 0.0

        return base + emotion_bonus + access_bonus - age_penalty

    def _parse_dt(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
