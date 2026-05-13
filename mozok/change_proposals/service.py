from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import Session

from mozok.agent.service import AgentService
from mozok.db.models import AgentRecord
from mozok.memory.service import MemoryService
from mozok.schemas.memory import MemoryCreate
from mozok.schemas.procedural_skills import ProceduralSkillUsageCreate
from mozok.schemas.goals import AgentGoalPatch
from mozok.schemas.entity_state import EntityStatePatch
from mozok.schemas.knowledge_relations import KnowledgeRelationUpsert
from mozok.goals.service import GoalService
from mozok.entity_state.service import EntityStateService
from mozok.knowledge_relations.service import KnowledgeRelationService
from mozok.procedural_skills.service import ProceduralSkillService
from mozok.change_proposals.schemas import (
    ChangeOperation,
    ChangeProposalApplyResult,
    ChangeProposalAutoPolicyRequest,
    ChangeProposalAutoPolicyResponse,
    ChangeProposalCreate,
    ChangeProposalDecisionRequest,
    ChangeProposalDecisionResponse,
    ChangeProposalListResponse,
    ChangeProposalRead,
)

_RISK_ORDER = {"low": 1, "medium": 2, "high": 3}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_now() -> str:
    return utc_now().isoformat()


def _merge_dict(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    result = dict(base or {})
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge_dict(result[key], value)
        else:
            result[key] = value
    return result


class ChangeProposalService:
    """Safe proposal/approval layer for Mozok self-updates.

    V35 deliberately stores proposals in AgentRecord.metadata_json instead of adding
    a new SQL table. That keeps the patch backwards-compatible while giving every
    cognitive/reflection/maintenance layer the same review/apply surface.
    """

    METADATA_KEY = "change_proposals"

    def __init__(self, db: Session, memory_service: MemoryService | None = None):
        self.db = db
        self.memory_service = memory_service
        self.agent_service = AgentService(db)

    def _ensure_agent(self, agent_id: str) -> AgentRecord:
        return self.agent_service.get_or_create_default_agent(agent_id)

    def _metadata(self, agent: AgentRecord) -> dict[str, Any]:
        return dict(agent.metadata_json or {})

    def _raw_list(self, agent: AgentRecord) -> list[dict[str, Any]]:
        metadata = self._metadata(agent)
        proposals = metadata.get(self.METADATA_KEY) or []
        return list(proposals) if isinstance(proposals, list) else []

    def _save_raw_list(self, agent: AgentRecord, proposals: list[dict[str, Any]]) -> None:
        metadata = self._metadata(agent)
        metadata[self.METADATA_KEY] = proposals
        agent.metadata_json = metadata
        agent.updated_at = utc_now()
        self.db.add(agent)
        self.db.commit()
        self.db.refresh(agent)

    def _to_read(self, raw: dict[str, Any]) -> ChangeProposalRead:
        return ChangeProposalRead.model_validate(raw)

    def create(self, agent_id: str, request: ChangeProposalCreate) -> ChangeProposalRead:
        agent = self._ensure_agent(agent_id)
        now = utc_now()
        proposal = ChangeProposalRead(
            proposal_id=f"chg_{uuid4().hex[:16]}",
            agent_id=agent_id,
            proposal_type=request.proposal_type,
            summary=request.summary,
            rationale=request.rationale,
            risk_level=request.risk_level,
            operations=request.operations,
            approval_mode=request.approval_mode,
            source=request.source,
            metadata=request.metadata,
            status="pending",
            created_at=now,
            updated_at=now,
            notes=["Created as a safe change proposal. No operation has been applied yet."],
        )
        if request.store:
            proposals = self._raw_list(agent)
            proposals.append(proposal.model_dump(mode="json"))
            self._save_raw_list(agent, proposals)
        return proposal

    def list(self, agent_id: str, status: str | None = None, proposal_type: str | None = None) -> ChangeProposalListResponse:
        agent = self._ensure_agent(agent_id)
        items = [self._to_read(raw) for raw in self._raw_list(agent)]
        if status:
            items = [item for item in items if item.status == status]
        if proposal_type:
            items = [item for item in items if item.proposal_type == proposal_type]
        return ChangeProposalListResponse(agent_id=agent_id, proposals=items)

    def apply(self, agent_id: str, request: ChangeProposalDecisionRequest) -> ChangeProposalDecisionResponse:
        agent = self._ensure_agent(agent_id)
        raw_items = self._raw_list(agent)
        selected_ids = set(request.proposal_ids or [])
        max_risk = _RISK_ORDER.get(request.max_risk_level, 3)
        changed = False
        results: list[ChangeProposalApplyResult] = []
        updated: list[dict[str, Any]] = []

        for raw in raw_items:
            proposal = self._to_read(raw)
            matches_id = not selected_ids or proposal.proposal_id in selected_ids
            matches_type = request.proposal_type is None or proposal.proposal_type == request.proposal_type
            allowed_risk = _RISK_ORDER.get(proposal.risk_level, 3) <= max_risk
            if proposal.status != "pending" or not matches_id or not matches_type or not allowed_risk:
                updated.append(raw)
                continue

            result = self._apply_one(agent=agent, proposal=proposal, dry_run=request.dry_run)
            if request.note:
                result.notes.append(request.note)
            results.append(result)
            if not request.dry_run:
                proposal.status = result.status
                proposal.applied_at = utc_now() if result.status == "applied" else proposal.applied_at
                proposal.updated_at = utc_now()
                proposal.applied_operation_count = result.applied_operation_count
                proposal.rollback_snapshot = result.rollback_snapshot
                proposal.notes.extend(result.notes)
                raw = proposal.model_dump(mode="json")
                changed = True
            updated.append(raw)

        if not request.dry_run and changed:
            self._save_raw_list(agent, updated)
        return ChangeProposalDecisionResponse(agent_id=agent_id, dry_run=request.dry_run, changed=changed, results=results)

    def reject(self, agent_id: str, request: ChangeProposalDecisionRequest) -> ChangeProposalDecisionResponse:
        agent = self._ensure_agent(agent_id)
        raw_items = self._raw_list(agent)
        selected_ids = set(request.proposal_ids or [])
        changed = False
        results: list[ChangeProposalApplyResult] = []
        updated: list[dict[str, Any]] = []

        for raw in raw_items:
            proposal = self._to_read(raw)
            matches_id = not selected_ids or proposal.proposal_id in selected_ids
            matches_type = request.proposal_type is None or proposal.proposal_type == request.proposal_type
            if proposal.status == "pending" and matches_id and matches_type:
                result = ChangeProposalApplyResult(
                    proposal_id=proposal.proposal_id,
                    status="rejected",
                    notes=[request.note or "Rejected by review workflow."],
                )
                results.append(result)
                if not request.dry_run:
                    proposal.status = "rejected"
                    proposal.rejected_at = utc_now()
                    proposal.updated_at = utc_now()
                    proposal.notes.extend(result.notes)
                    raw = proposal.model_dump(mode="json")
                    changed = True
            updated.append(raw)

        if not request.dry_run and changed:
            self._save_raw_list(agent, updated)
        return ChangeProposalDecisionResponse(agent_id=agent_id, dry_run=request.dry_run, changed=changed, results=results)

    def auto_apply(self, agent_id: str, request: ChangeProposalAutoPolicyRequest) -> ChangeProposalAutoPolicyResponse:
        if request.approval_mode == "dry_run_only":
            return ChangeProposalAutoPolicyResponse(
                agent_id=agent_id,
                approval_mode=request.approval_mode,
                dry_run=True,
                notes=["Policy is dry_run_only; no proposals were applied."],
            )
        if request.approval_mode == "manual_review":
            return ChangeProposalAutoPolicyResponse(
                agent_id=agent_id,
                approval_mode=request.approval_mode,
                dry_run=request.dry_run,
                notes=["Policy is manual_review; no proposals were auto-applied."],
            )
        max_risk = "low" if request.approval_mode == "apply_low_risk" else "medium"
        pending = self.list(agent_id, status="pending", proposal_type=request.proposal_type).proposals[: request.max_to_apply]
        if not pending:
            return ChangeProposalAutoPolicyResponse(agent_id=agent_id, approval_mode=request.approval_mode, dry_run=request.dry_run)
        response = self.apply(
            agent_id,
            ChangeProposalDecisionRequest(
                proposal_ids=[item.proposal_id for item in pending],
                max_risk_level=max_risk,
                dry_run=request.dry_run,
            ),
        )
        return ChangeProposalAutoPolicyResponse(
            agent_id=agent_id,
            approval_mode=request.approval_mode,
            dry_run=request.dry_run,
            applied_count=sum(1 for item in response.results if item.status == "applied"),
            skipped_count=max(0, len(pending) - len(response.results)),
            results=response.results,
        )

    def _apply_one(self, agent: AgentRecord, proposal: ChangeProposalRead, dry_run: bool) -> ChangeProposalApplyResult:
        snapshot = self._snapshot(agent, proposal)
        notes: list[str] = []
        applied = 0
        skipped = 0
        if dry_run:
            return ChangeProposalApplyResult(
                proposal_id=proposal.proposal_id,
                status="pending",
                applied_operation_count=0,
                skipped_operation_count=len(proposal.operations),
                rollback_snapshot=snapshot,
                notes=["Dry run: proposal was not modified or applied."],
            )

        for operation in proposal.operations:
            ok, note = self._apply_operation(agent=agent, operation=operation)
            if ok:
                applied += 1
            else:
                skipped += 1
            notes.append(note)
        return ChangeProposalApplyResult(
            proposal_id=proposal.proposal_id,
            status="applied" if applied > 0 and skipped == 0 else "pending",
            applied_operation_count=applied,
            skipped_operation_count=skipped,
            rollback_snapshot=snapshot,
            notes=notes,
        )

    def _snapshot(self, agent: AgentRecord, proposal: ChangeProposalRead) -> dict[str, Any]:
        return {
            "agent_id": agent.id,
            "agent_metadata_before": deepcopy(agent.metadata_json or {}),
            "operation_summaries": [op.summary or op.operation_type for op in proposal.operations],
            "created_at": _iso_now(),
        }

    def _apply_operation(self, agent: AgentRecord, operation: ChangeOperation) -> tuple[bool, str]:
        if operation.operation_type == "no_op":
            return True, "No-op accepted."

        if operation.operation_type == "update_agent_metadata":
            patch = dict(operation.payload.get("metadata_patch") or operation.payload or {})
            metadata = _merge_dict(dict(agent.metadata_json or {}), patch)
            agent.metadata_json = metadata
            agent.updated_at = utc_now()
            self.db.add(agent)
            self.db.commit()
            return True, "Merged metadata patch into agent metadata."

        if operation.operation_type == "add_memory":
            if self.memory_service is None:
                return False, "MemoryService is unavailable; cannot add memory."
            payload = dict(operation.payload or {})
            payload.setdefault("agent_id", agent.id)
            payload.setdefault("memory_type", "episodic")
            payload.setdefault("importance", 4)
            payload.setdefault("emotional_weight", 0.0)
            memory = self.memory_service.add_memory(MemoryCreate(**payload))
            return True, f"Created memory {memory.id}."

        if operation.operation_type == "update_goal":
            payload = dict(operation.payload or {})
            goal_id = payload.pop("goal_id", None) or operation.target_id
            patch = payload.pop("patch", payload)
            if goal_id is None:
                return False, "Missing goal_id for goal update."
            record = GoalService(self.db).patch(int(goal_id), AgentGoalPatch(**dict(patch or {})))
            if record is None:
                return False, f"Goal {goal_id} was not found."
            return True, f"Updated goal {goal_id}."

        if operation.operation_type == "update_entity_state":
            payload = dict(operation.payload or {})
            state_id = payload.pop("state_id", None) or operation.target_id
            patch = payload.pop("patch", payload)
            if state_id is None:
                return False, "Missing state_id for entity-state update."
            record = EntityStateService(self.db).patch(int(state_id), EntityStatePatch(**dict(patch or {})))
            if record is None:
                return False, f"Entity state {state_id} was not found."
            return True, f"Updated entity state {state_id}."

        if operation.operation_type == "add_knowledge_relation":
            payload = dict(operation.payload or {})
            payload.setdefault("agent_id", agent.id)
            relation = KnowledgeRelationService(self.db).upsert(KnowledgeRelationUpsert(**payload))
            return True, f"Upserted knowledge relation {relation.id}."

        if operation.operation_type == "record_skill_usage_result":
            payload = dict(operation.payload or {})
            skill_id = payload.pop("skill_id", None) or operation.target_id
            if not skill_id:
                return False, "Missing skill_id for skill usage result."
            response = ProceduralSkillService(self.db).record_usage_result(int(skill_id), ProceduralSkillUsageCreate(**payload))
            if response is None:
                return False, f"Procedural skill {skill_id} was not found."
            return True, f"Recorded procedural skill usage {response.usage.id}."

        return False, f"Unsupported operation type: {operation.operation_type}."
