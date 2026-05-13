from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from mozok.belief_revision.schemas import BeliefGraphEdge, BeliefGraphNode, BeliefGraphSummary, BeliefRevisionCandidate, BeliefRevisionRequest, BeliefRevisionResponse
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


def _memory_belief_confidence(memory: MemoryRecord) -> float:
    metadata = dict(memory.metadata_json or {})
    value = metadata.get("belief_confidence", metadata.get("confidence", None))
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return max(0.1, min(0.95, 0.35 + float(memory.importance or 5) / 20))


def _memory_source_trust(memory: MemoryRecord) -> float:
    metadata = dict(memory.metadata_json or {})
    value = metadata.get("source_trust", metadata.get("reliability", None))
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.55


def _temporal_status(memory: MemoryRecord, claim_valid_from: str | None, claim_valid_until: str | None) -> str:
    metadata = dict(memory.metadata_json or {})
    memory_valid_until = metadata.get("valid_until")
    memory_valid_from = metadata.get("valid_from")
    if claim_valid_from and memory_valid_until and str(memory_valid_until) <= str(claim_valid_from):
        return "outdated_by_claim"
    if claim_valid_until and memory_valid_from and str(memory_valid_from) >= str(claim_valid_until):
        return "future_or_separate_period"
    return "current"


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
            source_trust = _memory_source_trust(memory)
            temporal_status = _temporal_status(memory, request.claim.valid_from, request.claim.valid_until)
            if temporal_status == "outdated_by_claim" and relation in {"contradicts", "supersedes"}:
                reasons.append("temporal_context_claim_is_newer")
            suggested_delta = 0.0
            if relation == "supports":
                suggested_delta = round(0.05 * request.claim.confidence * request.claim.source_trust, 3)
            elif relation == "contradicts":
                suggested_delta = round(-0.15 * request.claim.confidence * request.claim.source_trust, 3)
            elif relation == "supersedes":
                suggested_delta = round(-0.1 * request.claim.confidence * request.claim.source_trust, 3)
            candidates.append(
                BeliefRevisionCandidate(
                    relation=relation,  # type: ignore[arg-type]
                    confidence=round(confidence, 3),
                    memory_id=memory.id,
                    memory_type=memory.memory_type,
                    memory_content=memory.content,
                    token_overlap=round(ov, 3),
                    source_trust=source_trust,
                    temporal_status=temporal_status,
                    suggested_confidence_delta=suggested_delta,
                    valid_from=dict(memory.metadata_json or {}).get("valid_from"),
                    valid_until=dict(memory.metadata_json or {}).get("valid_until"),
                    reasons=reasons,
                )
            )

        candidates.sort(key=lambda item: (item.relation != "contradicts", -item.confidence, -(item.token_overlap or 0)))
        action = self._recommended_action(candidates)
        belief_graph = self._belief_graph(agent_id, request, candidates)
        response = BeliefRevisionResponse(
            agent_id=agent_id,
            read_only=not request.create_change_proposal,
            claim=request.claim,
            candidates=candidates,
            recommended_action=action,
            belief_graph=belief_graph,
            notes=["Belief Graph V2 is review-first: it suggests confidence/temporal/source-trust effects and relation edges without deleting memories."],
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

    def _belief_graph(self, agent_id: str, request: BeliefRevisionRequest, candidates: list[BeliefRevisionCandidate]) -> BeliefGraphSummary:
        claim_node = BeliefGraphNode(
            node_type="claim",
            node_id="incoming_claim",
            content=request.claim.content,
            confidence=request.claim.confidence,
            source=request.claim.source,
            source_trust=request.claim.source_trust,
            temporal_status="incoming",
            valid_from=request.claim.valid_from,
            valid_until=request.claim.valid_until,
            metadata=request.claim.metadata,
        )
        nodes = [claim_node]
        edges: list[BeliefGraphEdge] = []
        payloads: list[dict[str, Any]] = []
        for candidate in candidates:
            if candidate.memory_id is None:
                continue
            memory_node_id = f"memory:{candidate.memory_id}"
            nodes.append(
                BeliefGraphNode(
                    node_type="memory",
                    node_id=memory_node_id,
                    content=candidate.memory_content or "",
                    confidence=candidate.confidence,
                    source=candidate.memory_type or "memory",
                    source_trust=candidate.source_trust,
                    temporal_status=candidate.temporal_status,
                    valid_from=candidate.valid_from,
                    valid_until=candidate.valid_until,
                )
            )
            effect = "raise_confidence" if candidate.relation == "supports" else "weaken_or_contextualise_existing_belief" if candidate.relation in {"contradicts", "supersedes"} else "review"
            edges.append(
                BeliefGraphEdge(
                    source_node_id="incoming_claim",
                    relation=candidate.relation,
                    target_node_id=memory_node_id,
                    strength=max(0.0, min(1.0, candidate.token_overlap)),
                    confidence=candidate.confidence,
                    temporal_relation=candidate.temporal_status,
                    recommended_effect=effect,
                    reasons=list(candidate.reasons),
                )
            )
            if candidate.relation in {"contradicts", "supersedes", "supports"}:
                payloads.append(
                    {
                        "agent_id": agent_id,
                        "world_id": request.world_id,
                        "source_type": "claim",
                        "source_id": "incoming_claim",
                        "relation_type": candidate.relation,
                        "target_type": "memory",
                        "target_id": str(candidate.memory_id),
                        "strength": max(0.0, min(1.0, candidate.token_overlap)),
                        "confidence": candidate.confidence,
                        "description": f"Belief Graph V2 suggested {candidate.relation} relation from incoming claim to memory {candidate.memory_id}.",
                        "evidence": {"reasons": candidate.reasons, "source_trust": candidate.source_trust, "temporal_status": candidate.temporal_status},
                        "metadata": {"source": "belief_graph_v2", "suggested_confidence_delta": candidate.suggested_confidence_delta},
                        "validate_nodes": False,
                    }
                )
        return BeliefGraphSummary(nodes=nodes, edges=edges, recommended_relation_payloads=payloads)

    def _create_proposal(self, agent_id: str, request: BeliefRevisionRequest, response: BeliefRevisionResponse):
        high_conflict = [item for item in response.candidates if item.relation in {"contradicts", "supersedes"}]
        operations = [
            ChangeOperation(
                operation_type="update_agent_metadata",
                target_type="agent",
                summary="Store latest belief graph preview for human or policy review",
                risk_level="low",
                payload={
                    "metadata_patch": {
                        "belief_revision": {
                            "last_claim": request.claim.model_dump(mode="json"),
                            "recommended_action": response.recommended_action,
                            "conflict_memory_ids": [item.memory_id for item in high_conflict if item.memory_id is not None],
                            "belief_graph_edge_count": len(response.belief_graph.edges),
                        }
                    }
                },
            )
        ]
        for payload in response.belief_graph.recommended_relation_payloads[:10]:
            operations.append(
                ChangeOperation(
                    operation_type="add_knowledge_relation",
                    target_type="knowledge_relation",
                    summary=f"Create reviewed belief graph edge: {payload.get('relation_type')}",
                    risk_level="medium" if payload.get("relation_type") in {"contradicts", "supersedes"} else "low",
                    payload=payload,
                )
            )
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
