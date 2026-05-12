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
                        proposal_type="reflection",
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
