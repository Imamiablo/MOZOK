from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from mozok.change_proposals.schemas import (
    ChangeOperation,
    ChangeProposalAutoPolicyRequest,
    ChangeProposalCreate,
)
from mozok.change_proposals.service import ChangeProposalService
from mozok.memory.service import MemoryService
from mozok.reflection.schemas import ReflectionRequest, ReflectionResponse, ReflectionSignal


def _compact(value: Any, max_chars: int = 420) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _looks_like_belief_revision(text: str) -> bool:
    lowered = str(text or "").lower()
    markers = ["actually", "correction", "not true", "no longer", "anymore", "instead", "now", "насправді", "не так", "тепер", "більше не"]
    return any(marker in lowered for marker in markers)


def _winning_skill_id(cognitive_field: dict[str, Any] | None) -> int | None:
    if not cognitive_field:
        return None
    candidates = cognitive_field.get("candidates") or []
    top_ids = []
    broadcast = cognitive_field.get("broadcast") or {}
    if broadcast.get("top_thought_ids"):
        top_ids.extend(broadcast.get("top_thought_ids") or [])
    if cognitive_field.get("winning_thought_id"):
        top_ids.insert(0, cognitive_field.get("winning_thought_id"))
    for thought_id in top_ids:
        if isinstance(thought_id, str) and thought_id.startswith("skill:"):
            try:
                return int(thought_id.split(":", 1)[1])
            except ValueError:
                continue
    for candidate in candidates:
        if candidate.get("thought_type") == "use_skill" and str(candidate.get("source_id") or "").isdigit():
            return int(candidate["source_id"])
    return None


class ReflectionService:
    """Post-turn reflection layer.

    The service analyses one completed turn and creates safe proposals. It does
    not directly mutate memory, skills, or agent metadata except through the
    ChangeProposalService approval workflow.
    """

    def __init__(self, db: Session, memory_service: MemoryService | None = None):
        self.db = db
        self.memory_service = memory_service
        self.proposals = ChangeProposalService(db=db, memory_service=memory_service)

    def reflect(self, request: ReflectionRequest) -> ReflectionResponse:
        signals = self._signals(request)
        proposals = []
        auto_applied_count = 0
        notes = ["Reflection generated safe proposals; no direct writes were performed by reflection itself."]

        if request.create_change_proposals:
            for proposal_request in self._proposal_requests(request, signals):
                proposals.append(self.proposals.create(request.agent_id, proposal_request))

            if request.auto_apply and proposals:
                auto = self.proposals.auto_apply(
                    request.agent_id,
                    ChangeProposalAutoPolicyRequest(
                        approval_mode=request.approval_mode,
                        # Apply all freshly generated reflection proposal families, not only the legacy
                        # generic ``reflection`` proposal type. This keeps V46 first-class goal/entity/
                        # belief proposals eligible for the same safe auto-policy path.
                        proposal_type=None,
                        dry_run=False,
                    ),
                )
                auto_applied_count = auto.applied_count
                notes.extend(auto.notes)

        return ReflectionResponse(
            agent_id=request.agent_id,
            session_id=request.session_id,
            read_only=not request.create_change_proposals,
            proposal_count=len(proposals),
            auto_applied_count=auto_applied_count,
            signals=signals,
            proposals=proposals,
            notes=notes,
        )

    def _signals(self, request: ReflectionRequest) -> list[ReflectionSignal]:
        signals: list[ReflectionSignal] = []
        if request.user_message:
            signals.append(
                ReflectionSignal(
                    signal_type="turn_summary",
                    summary=_compact(f"User asked: {request.user_message} | Assistant replied: {request.assistant_response}", request.max_summary_chars),
                    confidence=0.75,
                    evidence=["user_message", "assistant_response"],
                )
            )
        cognitive = request.cognitive_field or {}
        broadcast = cognitive.get("broadcast") or {}
        if broadcast.get("selected_label") or broadcast.get("prompt_guidance"):
            signals.append(
                ReflectionSignal(
                    signal_type="cognitive_broadcast",
                    summary=_compact(broadcast.get("prompt_guidance") or broadcast.get("selected_label"), request.max_summary_chars),
                    confidence=0.8,
                    evidence=[str(cognitive.get("winning_thought_id") or "broadcast")],
                )
            )
        if request.outcome != "unknown" or request.feedback:
            signals.append(
                ReflectionSignal(
                    signal_type="outcome_feedback",
                    summary=_compact(f"Outcome: {request.outcome}. Feedback: {request.feedback}"),
                    confidence=0.7,
                    evidence=["explicit_reflection_feedback"],
                )
            )
        for hint in request.goal_update_hints:
            signals.append(
                ReflectionSignal(
                    signal_type="goal_update_hint",
                    summary=_compact(hint.rationale or f"Goal update requested for goal_id={hint.goal_id}: {hint.patch}"),
                    confidence=0.8,
                    evidence=["reflection_goal_update_hint"],
                )
            )
        for hint in request.entity_state_update_hints:
            signals.append(
                ReflectionSignal(
                    signal_type="entity_state_update_hint",
                    summary=_compact(hint.rationale or f"Entity-state update requested for state_id={hint.state_id}: {hint.patch}"),
                    confidence=0.8,
                    evidence=["reflection_entity_state_update_hint"],
                )
            )
        for trigger in request.belief_revision_triggers:
            signals.append(
                ReflectionSignal(
                    signal_type="belief_revision_trigger",
                    summary=_compact(trigger.claim_content),
                    confidence=trigger.confidence,
                    evidence=["reflection_belief_revision_trigger"],
                )
            )
        if request.auto_detect_belief_revision and _looks_like_belief_revision(" ".join([request.user_message, request.assistant_response, request.feedback])):
            signals.append(
                ReflectionSignal(
                    signal_type="belief_revision_trigger",
                    summary=_compact(request.user_message or request.feedback or request.assistant_response),
                    confidence=0.55,
                    evidence=["auto_detected_correction_or_supersession_marker"],
                )
            )
        return signals

    def _proposal_requests(self, request: ReflectionRequest, signals: list[ReflectionSignal]) -> list[ChangeProposalCreate]:
        result: list[ChangeProposalCreate] = []
        if signals:
            content = "\n".join(f"- {signal.signal_type}: {signal.summary}" for signal in signals)
            result.append(
                ChangeProposalCreate(
                    proposal_type="reflection",
                    summary="Store compact post-turn reflection memory",
                    rationale="The turn produced a useful compact summary for future continuity.",
                    risk_level="low",
                    approval_mode=request.approval_mode,
                    source="reflection_loop",
                    store=request.store_proposals,
                    operations=[
                        ChangeOperation(
                            operation_type="add_memory",
                            target_type="memory",
                            summary="Create episodic reflection memory",
                            risk_level="low",
                            payload={
                                "agent_id": request.agent_id,
                                "session_id": request.session_id,
                                "content": content,
                                "memory_type": "episodic",
                                "importance": request.memory_importance,
                                "emotional_weight": 0.0,
                                "metadata": {
                                    "reflection_generated": True,
                                    "source": "reflection_loop",
                                    "used_memory_ids": request.used_memory_ids,
                                    "used_goal_ids": request.used_goal_ids,
                                    **request.metadata,
                                },
                            },
                        )
                    ],
                )
            )

        for hint in request.goal_update_hints:
            result.append(
                ChangeProposalCreate(
                    proposal_type="reflection_goal_update",
                    summary=f"Review reflected goal update for goal_id={hint.goal_id}",
                    rationale=hint.rationale or "Reflection detected a goal update hint that should be reviewed before it changes durable goal state.",
                    risk_level="medium",
                    approval_mode=request.approval_mode,
                    source="reflection_loop",
                    store=request.store_proposals,
                    metadata={"source_signal": "goal_update_hint", "goal_id": hint.goal_id},
                    operations=[
                        ChangeOperation(
                            operation_type="update_goal",
                            target_type="goal",
                            target_id=str(hint.goal_id) if hint.goal_id is not None else None,
                            summary="Apply reviewed goal patch",
                            risk_level="medium",
                            payload={"goal_id": hint.goal_id, "patch": dict(hint.patch or {})},
                        )
                    ],
                )
            )

        for hint in request.entity_state_update_hints:
            result.append(
                ChangeProposalCreate(
                    proposal_type="reflection_entity_state_update",
                    summary=f"Review reflected entity-state update for state_id={hint.state_id}",
                    rationale=hint.rationale or "Reflection detected an entity-state update hint that should be reviewed before it changes durable entity state.",
                    risk_level="medium",
                    approval_mode=request.approval_mode,
                    source="reflection_loop",
                    store=request.store_proposals,
                    metadata={"source_signal": "entity_state_update_hint", "state_id": hint.state_id},
                    operations=[
                        ChangeOperation(
                            operation_type="update_entity_state",
                            target_type="entity_state",
                            target_id=str(hint.state_id) if hint.state_id is not None else None,
                            summary="Apply reviewed entity-state patch",
                            risk_level="medium",
                            payload={"state_id": hint.state_id, "patch": dict(hint.patch or {})},
                        )
                    ],
                )
            )

        if request.belief_revision_triggers:
            trigger_payloads = [
                {
                    "claim_content": trigger.claim_content,
                    "source": trigger.source,
                    "confidence": trigger.confidence,
                    "world_id": trigger.world_id,
                    "tags": list(trigger.tags or []),
                    "metadata": dict(trigger.metadata or {}),
                }
                for trigger in request.belief_revision_triggers
            ]
            result.append(
                ChangeProposalCreate(
                    proposal_type="reflection_belief_revision",
                    summary="Review reflected belief revision trigger",
                    rationale="Reflection detected a possible correction or supersession. Keep it reviewable before belief graph state is updated.",
                    risk_level="medium",
                    approval_mode=request.approval_mode,
                    source="reflection_loop",
                    store=request.store_proposals,
                    metadata={"source_signal": "belief_revision_trigger", "trigger_count": len(trigger_payloads)},
                    operations=[
                        ChangeOperation(
                            operation_type="update_agent_metadata",
                            target_type="agent",
                            summary="Queue belief revision trigger metadata for reviewed follow-up",
                            risk_level="medium",
                            payload={
                                "metadata_patch": {
                                    "belief_revision": {
                                        "pending_reflection_triggers": trigger_payloads,
                                        "last_reflection_trigger": trigger_payloads[-1] if trigger_payloads else {},
                                    }
                                }
                            },
                        )
                    ],
                )
            )

        result.append(
            ChangeProposalCreate(
                proposal_type="reflection",
                summary="Update last reflection metadata",
                rationale="Keep a lightweight agent-local pointer to the most recent reflection without changing durable knowledge directly.",
                risk_level="low",
                approval_mode=request.approval_mode,
                source="reflection_loop",
                store=request.store_proposals,
                operations=[
                    ChangeOperation(
                        operation_type="update_agent_metadata",
                        target_type="agent",
                        summary="Store last reflection summary in agent metadata",
                        risk_level="low",
                        payload={
                            "metadata_patch": {
                                "reflection": {
                                    "last_session_id": request.session_id,
                                    "last_outcome": request.outcome,
                                    "last_summary": signals[0].summary if signals else "",
                                }
                            }
                        },
                    )
                ],
            )
        )

        skill_id = _winning_skill_id(request.cognitive_field)
        if skill_id is not None:
            outcome = request.outcome if request.outcome in {"success", "neutral", "failure"} else "neutral"
            result.append(
                ChangeProposalCreate(
                    proposal_type="reflection",
                    summary="Record procedural skill outcome from reflection",
                    rationale="A skill candidate participated in the cognitive broadcast and can receive safe usage evidence.",
                    risk_level="low",
                    approval_mode=request.approval_mode,
                    source="reflection_loop",
                    store=request.store_proposals,
                    operations=[
                        ChangeOperation(
                            operation_type="record_skill_usage_result",
                            target_type="procedural_skill",
                            target_id=str(skill_id),
                            summary="Record reflected procedural skill usage",
                            risk_level="low",
                            payload={
                                "skill_id": skill_id,
                                "session_id": request.session_id,
                                "context": _compact(request.user_message, 240),
                                "outcome": outcome,
                                "feedback": request.feedback,
                                "learned_note": "",
                                "apply_learned_note": False,
                                "metadata": {"source": "reflection_loop"},
                            },
                        )
                    ],
                )
            )
        return result
