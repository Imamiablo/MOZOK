from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from mozok.agent.service import AgentService
from mozok.agent_modes.service import AgentModeService
from mozok.change_proposals.schemas import ChangeOperation, ChangeProposalCreate
from mozok.change_proposals.service import ChangeProposalService
from mozok.self_model.schemas import SelfModelProposalRequest, SelfModelProposalResponse, SelfModelRequest, SelfModelResponse, SelfModelState


def _compact(text: str, limit: int = 240) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


class SelfModelService:
    """Build a functional self-model without claiming phenomenal consciousness.

    The self-model is an operational state summary: role, task, focus,
    uncertainty, constraints, and current limitations. It can feed prompts,
    reflection, and safe change proposals.
    """

    def __init__(self, db: Session | None = None):
        self.db = db

    def preview(self, agent_id: str, request: SelfModelRequest) -> SelfModelResponse:
        mode_profile = self._mode(agent_id, request.agent_mode)
        broadcast = (request.cognitive_field or {}).get("broadcast") or {}
        active_focus = _compact(broadcast.get("working_memory_line") or broadcast.get("prompt_guidance") or request.user_message, 280)
        confidence = request.confidence if request.confidence is not None else self._confidence_from_cognition(request.cognitive_field)
        uncertainty = request.uncertainty if request.uncertainty is not None else round(max(0.0, 1.0 - confidence), 3)

        constraints = list(mode_profile.get("prompt_guidance") or [])[:4]
        limitations = ["External tools and world actions require an adapter or approval layer."]
        if not request.perception_summary and mode_profile.get("enable_perception_by_default"):
            limitations.append("No fresh perception summary was provided for this turn.")
        if request.action_plan:
            selected = request.action_plan.get("selected_action") or {}
            if selected.get("approval_required"):
                limitations.append("Selected action intent requires approval before execution.")

        needs: list[str] = []
        if uncertainty >= 0.65:
            needs.append("Ask for clarification or prefer low-risk responses.")
        if mode_profile.get("can_execute_actions") and not request.action_plan:
            needs.append("Generate or receive an action plan before attempting world/tool changes.")

        state = SelfModelState(
            agent_id=agent_id,
            mode=mode_profile.get("mode", request.agent_mode or "assistant"),
            self_description=self._description(mode_profile),
            current_task=_compact(request.current_task or request.user_message, 220),
            active_focus=active_focus,
            confidence=confidence,
            uncertainty=uncertainty,
            limitations=limitations,
            needs=needs,
            behavioural_constraints=constraints,
            reflective_notes=[_compact(request.reflection_summary, 240)] if request.reflection_summary else [],
            metadata=request.metadata,
        )
        return SelfModelResponse(
            agent_id=agent_id,
            read_only=True,
            state=state,
            prompt_block=self._prompt_block(state),
            notes=["Self-model is a functional operational state, not a durable identity claim by itself."],
        )

    def propose_update(self, agent_id: str, request: SelfModelProposalRequest) -> SelfModelProposalResponse:
        response = self.preview(agent_id, request)
        proposal = ChangeProposalCreate(
            proposal_type="self_model",
            summary="Update functional self-model metadata",
            rationale="The current turn produced a compact operational self-state that may help future continuity.",
            risk_level="low",
            approval_mode=request.approval_mode,  # type: ignore[arg-type]
            source="self_model",
            store=request.store_proposal,
            operations=[
                ChangeOperation(
                    operation_type="update_agent_metadata",
                    target_type="agent",
                    summary="Store latest functional self-model snapshot",
                    risk_level="low",
                    payload={"metadata_patch": {"self_model": response.state.model_dump(mode="json")}},
                )
            ],
        )
        stored = None
        if self.db is not None:
            stored = ChangeProposalService(self.db).create(agent_id, proposal).model_dump(mode="json")
        else:
            stored = proposal.model_dump(mode="json")
        return SelfModelProposalResponse(agent_id=agent_id, self_model=response, proposal=stored)

    def _mode(self, agent_id: str, explicit_mode: str | None) -> dict[str, Any]:
        if self.db is None:
            return {"mode": explicit_mode or "assistant", "prompt_guidance": []}
        agent = AgentService(self.db).get_or_create_default_agent(agent_id)
        return AgentModeService().resolve(agent, agent_mode=explicit_mode).profile.model_dump(mode="json")

    def _confidence_from_cognition(self, cognitive_field: dict[str, Any] | None) -> float:
        if not cognitive_field:
            return 0.55
        winner = cognitive_field.get("winning_score")
        candidates = cognitive_field.get("candidate_count") or len(cognitive_field.get("candidates") or [])
        if isinstance(winner, (int, float)):
            return round(max(0.1, min(0.95, 0.45 + float(winner) / 25 - max(0, candidates - 4) * 0.02)), 3)
        return 0.6

    def _description(self, profile: dict[str, Any]) -> str:
        mode = profile.get("mode", "assistant")
        label = profile.get("label") or mode
        return f"{label}: {profile.get('description') or 'Mozok agent operating profile.'}"

    def _prompt_block(self, state: SelfModelState) -> str:
        lines = ["Self-model / reflective state:", f"- Mode: {state.mode}"]
        if state.current_task:
            lines.append(f"- Current task: {state.current_task}")
        if state.active_focus:
            lines.append(f"- Active focus: {state.active_focus}")
        lines.append(f"- Confidence: {state.confidence:.2f}; uncertainty: {state.uncertainty:.2f}")
        for item in state.needs[:3]:
            lines.append(f"- Need: {item}")
        for item in state.limitations[:3]:
            lines.append(f"- Limitation: {item}")
        return "\n".join(lines)
