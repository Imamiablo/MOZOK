from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from mozok.belief_revision.schemas import BeliefRevisionCandidate, BeliefRevisionRequest, BeliefRevisionResponse
from mozok.change_proposals.schemas import ChangeOperation, ChangeProposalCreate
from mozok.change_proposals.service import ChangeProposalService
from mozok.db.models import MemoryRecord

_NEGATIONS = {"not", "never", "no", "without", "isn't", "wasn't", "не", "ніколи", "немає", "нема"}
_SUPERSEDE_MARKERS = {"now", "currently", "anymore", "instead", "тепер", "зараз", "більше"}


def _tokens(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[a-zA-Zа-яА-ЯіїєґІЇЄҐ0-9_]+", text or "") if len(w) > 2}


def _negated(text: str) -> bool:
    return bool(_tokens(text).intersection(_NEGATIONS))


def _overlap(a: str, b: str) -> float:
    aa = _tokens(a)
    bb = _tokens(b)
    if not aa or not bb:
        return 0.0
    return len(aa.intersection(bb)) / max(1, min(len(aa), len(bb)))


class BeliefRevisionService:
    """Preview contradictions/supersession without rewriting memories.

    This MVP is intentionally conservative and explainable. It uses lexical
    overlap and negation/supersession markers; future versions can add embedding
    and LLM-supported checks behind the same response schema.
    """

    def __init__(self, db: Session):
        self.db = db

    def preview(self, agent_id: str, request: BeliefRevisionRequest) -> BeliefRevisionResponse:
        memories = self._memories(agent_id, request)
        candidates: list[BeliefRevisionCandidate] = []
        claim_text = request.claim.content
        claim_negated = _negated(claim_text)
        claim_tokens = _tokens(claim_text)

        for memory in memories:
            ov = _overlap(claim_text, memory.content)
            if ov < request.min_token_overlap:
                continue
            memory_negated = _negated(memory.content)
            reasons = [f"token_overlap={ov:.2f}"]
            relation = "supports"
            confidence = min(0.95, 0.45 + ov * 0.5)
            if claim_negated != memory_negated and ov >= request.min_token_overlap:
                relation = "contradicts"
                confidence = min(0.95, 0.55 + ov * 0.4)
                reasons.append("negation_mismatch")
            if claim_tokens.intersection(_SUPERSEDE_MARKERS) and ov >= request.min_token_overlap:
                relation = "supersedes" if relation != "contradicts" else "contradicts"
                reasons.append("supersession_marker")
            candidates.append(
                BeliefRevisionCandidate(
                    relation=relation,  # type: ignore[arg-type]
                    confidence=round(confidence, 3),
                    memory_id=memory.id,
                    memory_type=memory.memory_type,
                    memory_content=memory.content,
                    token_overlap=round(ov, 3),
                    reasons=reasons,
                )
            )

        candidates.sort(key=lambda item: (item.relation != "contradicts", -item.confidence, -(item.token_overlap or 0)))
        action = self._recommended_action(candidates)
        response = BeliefRevisionResponse(
            agent_id=agent_id,
            read_only=not request.create_change_proposal,
            claim=request.claim,
            candidates=candidates,
            recommended_action=action,
            notes=["Belief revision MVP is review-first and does not delete or rewrite memories automatically."],
        )
        if request.create_change_proposal:
            response.proposal = self._create_proposal(agent_id, request, response).model_dump(mode="json")
        return response

    def _memories(self, agent_id: str, request: BeliefRevisionRequest) -> list[MemoryRecord]:
        query = self.db.query(MemoryRecord).filter(MemoryRecord.agent_id == agent_id)
        if not request.include_inactive:
            query = query.filter(MemoryRecord.active == True)  # noqa: E712
        return query.order_by(MemoryRecord.updated_at.desc()).limit(request.memory_limit).all()

    def _recommended_action(self, candidates: list[BeliefRevisionCandidate]) -> str:
        if any(item.relation == "contradicts" and item.confidence >= 0.65 for item in candidates):
            return "review_contradiction"
        if any(item.relation == "supersedes" and item.confidence >= 0.65 for item in candidates):
            return "review_supersession"
        if any(item.relation == "supports" for item in candidates):
            return "keep_existing_belief"
        return "consider_new_memory"

    def _create_proposal(self, agent_id: str, request: BeliefRevisionRequest, response: BeliefRevisionResponse):
        high_conflict = [item for item in response.candidates if item.relation in {"contradicts", "supersedes"}]
        operations = [
            ChangeOperation(
                operation_type="update_agent_metadata",
                target_type="agent",
                summary="Store latest belief revision preview for human or policy review",
                risk_level="low",
                payload={
                    "metadata_patch": {
                        "belief_revision": {
                            "last_claim": request.claim.model_dump(mode="json"),
                            "recommended_action": response.recommended_action,
                            "conflict_memory_ids": [item.memory_id for item in high_conflict if item.memory_id is not None],
                        }
                    }
                },
            )
        ]
        proposal = ChangeProposalCreate(
            proposal_type="belief_revision",
            summary=f"Review belief update: {response.recommended_action}",
            rationale="A new claim may support, contradict, or supersede existing memories. Review before durable memory changes.",
            risk_level="medium" if high_conflict else "low",
            approval_mode=request.approval_mode,  # type: ignore[arg-type]
            source="belief_revision",
            store=request.store_proposal,
            metadata={"candidate_count": len(response.candidates), **request.metadata},
            operations=operations,
        )
        return ChangeProposalService(self.db).create(agent_id, proposal)
