from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from mozok.db.models import MemoryRecord
from mozok.knowledge_relations.models import KnowledgeRelationRecord
from mozok.memory.policy import (
    FORGET_ACTION_ARCHIVE,
    FORGET_ACTION_DECAY,
    FORGET_ACTION_HARD_DELETE,
    FORGET_ACTION_PROTECT,
    FORGET_ACTION_SOFT_DELETE,
    FORGET_ACTION_SUMMARIZE,
    FORGET_ACTION_SUMMARIZE_THEN_ARCHIVE,
)
from mozok.memory.service import MemoryService
from mozok.schemas.memory import (
    MemoryMaintenanceApplyRejectRequest,
    MemoryMaintenanceApplyRejectResponse,
    MemoryMaintenanceApplyRejectResult,
    MemoryMaintenanceSuggestionInput,
)


DESTRUCTIVE_ACTIONS = {
    FORGET_ACTION_ARCHIVE,
    FORGET_ACTION_DECAY,
    FORGET_ACTION_SOFT_DELETE,
    FORGET_ACTION_HARD_DELETE,
    FORGET_ACTION_SUMMARIZE_THEN_ARCHIVE,
}

MEMORY_NODE_TYPES = {"memory", "memory_record", "memoryrecord"}

PROTECTING_RELATION_TYPES = {
    "depends_on",
    "supports",
    "evidence_for",
    "source_for",
    "explains",
    "linked_to",
    "related_to",
    "mentions",
    "about",
    "known_by",
    "remembered_by",
}

ARCHIVE_FRIENDLY_RELATION_TYPES = {
    "duplicate_of",
    "summarised_by",
    "summarized_by",
    "superseded_by",
    "obsolete_after",
}


class MemoryMaintenanceApplyService:
    """Apply or reject selected maintenance suggestions.

    This is deliberately suggestion-driven rather than scheduler-driven. A UI or
    preview endpoint can pass selected suggestion objects here, then this service
    applies only those choices. SQL remains the source of truth and FAISS is
    rebuilt once at the end when required.
    """

    def __init__(self, db: Session, memory_service: MemoryService):
        self.db = db
        self.memory_service = memory_service

    def apply_suggestions(
        self,
        agent_id: str,
        request: MemoryMaintenanceApplyRejectRequest,
    ) -> MemoryMaintenanceApplyRejectResponse:
        selected = self._select_suggestions(request)
        results: list[MemoryMaintenanceApplyRejectResult] = []
        applied_count = 0
        relation_protected_count = 0
        skipped_count = 0

        for suggestion in selected:
            result = self._apply_one(agent_id, suggestion, request.override_relation_protection)
            results.append(result)
            if result.status == "applied":
                applied_count += 1
            if result.status == "relation_protected":
                relation_protected_count += 1
            if result.status in {"skipped", "not_found", "unsupported_action"}:
                skipped_count += 1

        rebuilt_index = False
        indexed_memories: int | None = None
        if request.rebuild_index and any(self._needs_index_rebuild(result.action) and result.changed for result in results):
            indexed_memories = self.memory_service.rebuild_index()
            rebuilt_index = True

        return MemoryMaintenanceApplyRejectResponse(
            agent_id=agent_id,
            mode="apply",
            selection=request.selection,
            requested_suggestions=len(request.suggestions),
            selected_suggestions=len(selected),
            applied=applied_count,
            rejected=0,
            skipped=skipped_count,
            relation_protected=relation_protected_count,
            rebuilt_index=rebuilt_index,
            indexed_memories=indexed_memories,
            results=results,
            notes=self._notes(results),
        )

    def reject_suggestions(
        self,
        agent_id: str,
        request: MemoryMaintenanceApplyRejectRequest,
    ) -> MemoryMaintenanceApplyRejectResponse:
        selected = self._select_suggestions(request)
        results: list[MemoryMaintenanceApplyRejectResult] = []
        rejected_count = 0
        skipped_count = 0

        for suggestion in selected:
            result = self._reject_one(agent_id, suggestion)
            results.append(result)
            if result.status == "rejected":
                rejected_count += 1
            if result.status in {"skipped", "not_found"}:
                skipped_count += 1

        return MemoryMaintenanceApplyRejectResponse(
            agent_id=agent_id,
            mode="reject",
            selection=request.selection,
            requested_suggestions=len(request.suggestions),
            selected_suggestions=len(selected),
            applied=0,
            rejected=rejected_count,
            skipped=skipped_count,
            relation_protected=0,
            rebuilt_index=False,
            indexed_memories=None,
            results=results,
            notes=self._notes(results),
        )

    def _select_suggestions(
        self,
        request: MemoryMaintenanceApplyRejectRequest,
    ) -> list[MemoryMaintenanceSuggestionInput]:
        if request.selection == "all":
            return list(request.suggestions)

        selected_ids = set(request.selected_suggestion_ids or [])
        if not selected_ids:
            return []

        return [suggestion for suggestion in request.suggestions if suggestion.suggestion_id in selected_ids]

    def _apply_one(
        self,
        agent_id: str,
        suggestion: MemoryMaintenanceSuggestionInput,
        override_relation_protection: bool,
    ) -> MemoryMaintenanceApplyRejectResult:
        action = suggestion.action
        target_ids = self._normalise_target_ids(suggestion.target_memory_ids)
        if not target_ids:
            return self._result(suggestion, "skipped", False, "Suggestion has no target_memory_ids.")

        records = self._load_agent_memories(agent_id, target_ids)
        if not records:
            return self._result(suggestion, "not_found", False, "No target memories were found for this agent.")

        relation_blocks = self._relation_blocks(agent_id, [record.id for record in records])
        if action in DESTRUCTIVE_ACTIONS and relation_blocks and not override_relation_protection:
            changed = False
            for record in records:
                if record.id not in relation_blocks:
                    continue
                self.memory_service._protect_record(  # noqa: SLF001 - deliberate service-level reuse.
                    record,
                    reason="maintenance_apply_relation_protection",
                )
                changed = True
            if changed:
                self.db.commit()

            protected_ids = sorted(relation_blocks.keys())
            return self._result(
                suggestion,
                "relation_protected",
                changed,
                "Suggestion was not applied because at least one target memory is linked by active knowledge relations.",
                target_memory_ids=protected_ids,
                relation_ids=sorted({relation_id for ids in relation_blocks.values() for relation_id in ids}),
            )

        if action == FORGET_ACTION_SUMMARIZE and len(records) > 1:
            summary = self.memory_service._create_summary_memory(  # noqa: SLF001 - deliberate service-level reuse.
                agent_id,
                records,
                trigger=f"maintenance_apply:{suggestion.suggestion_id}",
            )
            self.db.commit()
            return self._result(
                suggestion,
                "applied",
                True,
                f"Created semantic summary memory {summary.id}. Source memories remain active.",
                created_summary_ids=[summary.id],
            )

        if action == FORGET_ACTION_SUMMARIZE_THEN_ARCHIVE and len(records) > 1:
            summary = self.memory_service._create_summary_memory(  # noqa: SLF001
                agent_id,
                records,
                trigger=f"maintenance_apply:{suggestion.suggestion_id}",
            )
            for record in records:
                self.memory_service._archive_or_deactivate_record(  # noqa: SLF001
                    record,
                    action=FORGET_ACTION_ARCHIVE,
                    reason=suggestion.reason or f"maintenance_apply:{suggestion.suggestion_id}",
                )
            self.db.commit()
            return self._result(
                suggestion,
                "applied",
                True,
                f"Created semantic summary memory {summary.id}; source memories archived.",
                created_summary_ids=[summary.id],
            )

        supported_single_actions = {
            FORGET_ACTION_ARCHIVE,
            FORGET_ACTION_DECAY,
            FORGET_ACTION_HARD_DELETE,
            FORGET_ACTION_PROTECT,
            FORGET_ACTION_SOFT_DELETE,
            FORGET_ACTION_SUMMARIZE,
            FORGET_ACTION_SUMMARIZE_THEN_ARCHIVE,
        }
        if action not in supported_single_actions:
            return self._result(suggestion, "unsupported_action", False, f"Unsupported maintenance action: {action}")

        messages: list[str] = []
        changed = False
        created_summary_ids: list[int] = []
        for record in records:
            result = self.memory_service.forget_memory(
                memory_id=record.id,
                action=action,
                reason=suggestion.reason or f"maintenance_apply:{suggestion.suggestion_id}",
                decay_amount=suggestion.decay_amount,
                rebuild_index=False,
            )
            messages.append(result.get("message", ""))
            changed = changed or bool(result.get("changed"))
            message = result.get("message", "")
            created_summary_ids.extend(self._created_summary_ids_from_message(message))

        return self._result(
            suggestion,
            "applied" if changed else "skipped",
            changed,
            " ".join(message for message in messages if message).strip() or "No change was applied.",
            created_summary_ids=created_summary_ids,
        )

    def _reject_one(
        self,
        agent_id: str,
        suggestion: MemoryMaintenanceSuggestionInput,
    ) -> MemoryMaintenanceApplyRejectResult:
        target_ids = self._normalise_target_ids(suggestion.target_memory_ids)
        if not target_ids:
            return self._result(suggestion, "skipped", False, "Suggestion has no target_memory_ids.")

        records = self._load_agent_memories(agent_id, target_ids, include_inactive=True)
        if not records:
            return self._result(suggestion, "not_found", False, "No target memories were found for this agent.")

        now = datetime.now(timezone.utc).isoformat()
        for record in records:
            metadata = dict(record.metadata_json or {})
            metadata.setdefault("maintenance_rejections", [])
            metadata["maintenance_rejections"].append(
                {
                    "suggestion_id": suggestion.suggestion_id,
                    "action": suggestion.action,
                    "reason": suggestion.reason,
                    "rejected_at": now,
                }
            )
            record.metadata_json = metadata
            record.updated_at = datetime.now(timezone.utc)
        self.db.commit()

        return self._result(
            suggestion,
            "rejected",
            True,
            "Suggestion was recorded as rejected. No maintenance action was applied.",
        )

    def _load_agent_memories(
        self,
        agent_id: str,
        target_ids: list[int],
        include_inactive: bool = False,
    ) -> list[MemoryRecord]:
        query = self.db.query(MemoryRecord).filter(
            MemoryRecord.agent_id == agent_id,
            MemoryRecord.id.in_(target_ids),
        )
        if not include_inactive:
            query = query.filter(MemoryRecord.active == True)  # noqa: E712
        return query.all()

    def _relation_blocks(self, agent_id: str, memory_ids: list[int]) -> dict[int, list[int]]:
        if not memory_ids:
            return {}

        memory_id_strings = [str(memory_id) for memory_id in memory_ids]
        relations = (
            self.db.query(KnowledgeRelationRecord)
            .filter(
                KnowledgeRelationRecord.agent_id == agent_id,
                KnowledgeRelationRecord.active == True,  # noqa: E712
                or_(
                    and_(
                        KnowledgeRelationRecord.source_type.in_(MEMORY_NODE_TYPES),
                        KnowledgeRelationRecord.source_id.in_(memory_id_strings),
                    ),
                    and_(
                        KnowledgeRelationRecord.target_type.in_(MEMORY_NODE_TYPES),
                        KnowledgeRelationRecord.target_id.in_(memory_id_strings),
                    ),
                ),
            )
            .all()
        )

        blocked: dict[int, list[int]] = defaultdict(list)
        for relation in relations:
            relation_type = str(relation.relation_type or "").strip().lower()
            if relation_type in ARCHIVE_FRIENDLY_RELATION_TYPES:
                continue
            if relation_type not in PROTECTING_RELATION_TYPES and relation.confidence < 0.75:
                continue

            for memory_id in memory_ids:
                memory_id_string = str(memory_id)
                if (
                    relation.source_type in MEMORY_NODE_TYPES
                    and relation.source_id == memory_id_string
                ) or (
                    relation.target_type in MEMORY_NODE_TYPES
                    and relation.target_id == memory_id_string
                ):
                    blocked[memory_id].append(relation.id)
        return dict(blocked)

    def _normalise_target_ids(self, target_ids: list[int]) -> list[int]:
        normalised: list[int] = []
        for value in target_ids:
            try:
                normalised.append(int(value))
            except (TypeError, ValueError):
                continue
        return sorted(set(normalised))

    def _result(
        self,
        suggestion: MemoryMaintenanceSuggestionInput,
        status: str,
        changed: bool,
        message: str,
        target_memory_ids: list[int] | None = None,
        relation_ids: list[int] | None = None,
        created_summary_ids: list[int] | None = None,
    ) -> MemoryMaintenanceApplyRejectResult:
        return MemoryMaintenanceApplyRejectResult(
            suggestion_id=suggestion.suggestion_id,
            action=suggestion.action,
            target_memory_ids=target_memory_ids if target_memory_ids is not None else suggestion.target_memory_ids,
            status=status,
            changed=changed,
            message=message,
            relation_ids=relation_ids or [],
            created_summary_ids=created_summary_ids or [],
        )

    def _needs_index_rebuild(self, action: str) -> bool:
        return action in {
            FORGET_ACTION_ARCHIVE,
            FORGET_ACTION_SOFT_DELETE,
            FORGET_ACTION_HARD_DELETE,
            FORGET_ACTION_SUMMARIZE_THEN_ARCHIVE,
        }

    def _created_summary_ids_from_message(self, message: str) -> list[int]:
        parts = message.replace(";", " ").replace(".", " ").split()
        ids: list[int] = []
        for index, part in enumerate(parts):
            if part == "memory" and index + 1 < len(parts):
                try:
                    ids.append(int(parts[index + 1]))
                except ValueError:
                    continue
        return ids

    def _notes(self, results: list[MemoryMaintenanceApplyRejectResult]) -> list[str]:
        notes: list[str] = []
        if any(result.status == "relation_protected" for result in results):
            notes.append(
                "Some suggestions were blocked by relation-aware protection and the linked memories were protected instead."
            )
        if not results:
            notes.append("No suggestions were selected.")
        return notes
