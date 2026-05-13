from __future__ import annotations

import re
from typing import Any

from sqlalchemy.orm import Session

from mozok.agent.service import AgentService
from mozok.agent_modes.service import AgentModeService
from mozok.action_planning.schemas import (
    ActionIntent,
    ActionPlanRequest,
    ActionPlanResponse,
    ActionProposalRequest,
    ActionProposalResponse,
    ActionToolSpec,
)
from mozok.change_proposals.schemas import ChangeOperation, ChangeProposalCreate
from mozok.change_proposals.service import ChangeProposalService


_RISK_ORDER = {"low": 1, "medium": 2, "high": 3}


def _words(text: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[a-zA-Zа-яА-ЯіїєґІЇЄҐ0-9_]+", text or "") if len(w) > 2}


def _compact(text: str, limit: int = 260) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[: max(0, limit - 1)].rstrip() + "…"


class ActionPlanningService:
    """Read-only action/tool-intent planner.

    It deliberately produces intents, not real tool executions. Tool adapters,
    game engines, desktop apps, or future robotics layers can decide how to
    execute an approved intent.
    """

    def __init__(self, db: Session | None = None):
        self.db = db

    def plan(self, agent_id: str, request: ActionPlanRequest) -> ActionPlanResponse:
        mode = self._resolve_mode(agent_id, request.agent_mode)
        allowed = set(request.allowed_action_kinds or [])
        actions: list[ActionIntent] = []

        broadcast = (request.cognitive_field or {}).get("broadcast") or {}
        current_words = _words(" ".join([request.user_message, str(broadcast.get("prompt_guidance") or "")]))

        # Speaking/responding is always a safe baseline action.
        speak_score = 5.0 + min(4.0, len(current_words) / 8)
        if broadcast.get("selected_label"):
            speak_score += 2.0
        actions.append(
            ActionIntent(
                action_id="act_speak_response",
                action_kind="speak",
                label="Respond to the user",
                rationale=_compact(broadcast.get("prompt_guidance") or "Answer the current message using the resolved context."),
                risk_level="low",
                status="ready",
                score=round(speak_score, 3),
                evidence=["baseline_dialogue_action"],
                approval_required=False,
            )
        )

        # Optional tool/game/world actions are selected by keyword/tag overlap.
        for index, tool in enumerate(request.available_tools):
            if allowed and tool.action_kind not in allowed:
                continue
            overlap = current_words.intersection(_words(" ".join([tool.name, tool.description, " ".join(tool.tags)])))
            sensory_bonus = self._sensory_bonus(tool, request.sensory_inputs)
            mode_bonus = 1.5 if mode.get("can_execute_actions") else -1.0
            score = len(overlap) * 2.0 + sensory_bonus + mode_bonus
            if tool.action_kind in {"game_command", "world_event"} and mode.get("can_autonomously_tick"):
                score += 1.0
            if score <= 0:
                continue
            approval = tool.requires_approval or _RISK_ORDER.get(tool.risk_level, 3) >= 2 and request.require_approval_for_medium_risk
            actions.append(
                ActionIntent(
                    action_id=f"act_tool_{index}_{tool.name}",
                    action_kind=tool.action_kind,
                    label=f"Use tool: {tool.name}",
                    rationale=_compact(tool.description or f"Candidate tool intent for {tool.name}."),
                    tool_name=tool.name,
                    parameters={"source": "action_planning_mvp", "needs_adapter_execution": True},
                    risk_level=tool.risk_level,
                    status="needs_approval" if approval else "ready",
                    score=round(score, 3),
                    evidence=[f"keyword_overlap={sorted(overlap)}"] if overlap else ["mode_or_sensory_signal"],
                    approval_required=approval,
                )
            )

        # If a high-risk cognitive focus exists, explicitly emit a no-op/safety candidate.
        if "secret" in current_words or "danger" in current_words or "forbidden" in current_words:
            actions.append(
                ActionIntent(
                    action_id="act_no_op_safety_pause",
                    action_kind="no_op",
                    label="Pause before unsafe or secret-changing action",
                    rationale="The current focus may involve sensitive world knowledge or irreversible state changes.",
                    risk_level="low",
                    status="ready",
                    score=4.0,
                    evidence=["safety_keyword_detected"],
                    approval_required=False,
                )
            )

        actions.sort(key=lambda item: (-item.score, item.action_id))
        actions = actions[: request.max_candidates]
        selected = actions[0] if actions else None
        return ActionPlanResponse(
            agent_id=agent_id,
            read_only=True,
            selected_action_id=selected.action_id if selected else None,
            selected_action=selected,
            actions=actions,
            execution_policy={
                "mvp": True,
                "executes_tools": False,
                "adapter_required": True,
                "mode": mode.get("mode", "assistant"),
                "approval_for_medium_risk": request.require_approval_for_medium_risk,
            },
            notes=["Action Planning MVP returns intents only. It does not execute tools or mutate world state."],
        )

    def propose(self, agent_id: str, request: ActionProposalRequest) -> ActionProposalResponse:
        plan = self.plan(agent_id, request)
        if not plan.selected_action:
            return ActionProposalResponse(agent_id=agent_id, plan=plan, proposal=None)
        selected = plan.selected_action
        proposal = ChangeProposalCreate(
            proposal_type="action_intent",
            summary=f"Review action intent: {selected.label}",
            rationale=selected.rationale,
            risk_level=selected.risk_level,
            approval_mode=request.approval_mode,  # type: ignore[arg-type]
            source="action_planning",
            store=request.store_proposal,
            metadata={"selected_action_id": selected.action_id, "action_kind": selected.action_kind},
            operations=[
                ChangeOperation(
                    operation_type="update_agent_metadata",
                    target_type="agent",
                    summary="Store last proposed action intent for adapter/UI review",
                    risk_level="low",
                    payload={
                        "metadata_patch": {
                            "action_planning": {
                                "last_intent": selected.model_dump(mode="json"),
                                "last_plan_note": "Intent only; external adapter must execute if approved.",
                            }
                        }
                    },
                )
            ],
        )
        stored = None
        if self.db is not None:
            stored = ChangeProposalService(self.db).create(agent_id, proposal).model_dump(mode="json")
        else:
            stored = proposal.model_dump(mode="json")
        return ActionProposalResponse(agent_id=agent_id, plan=plan, proposal=stored)

    def _resolve_mode(self, agent_id: str, explicit_mode: str | None) -> dict[str, Any]:
        if self.db is None:
            return {"mode": explicit_mode or "assistant", "can_execute_actions": explicit_mode in {"simulacra_npc", "world_director", "tool_agent"}}
        agent = AgentService(self.db).get_or_create_default_agent(agent_id)
        resolved = AgentModeService().resolve(agent, agent_mode=explicit_mode)
        return resolved.profile.model_dump(mode="json")

    def _sensory_bonus(self, tool: ActionToolSpec, sensory_inputs: list[dict[str, Any]]) -> float:
        if not sensory_inputs:
            return 0.0
        haystack = _words(" ".join([tool.name, tool.description, " ".join(tool.tags)]))
        bonus = 0.0
        for item in sensory_inputs:
            overlap = haystack.intersection(_words(str(item.get("content") or "") + " " + " ".join(item.get("tags") or [])))
            if overlap:
                bonus += min(2.0, float(item.get("attention") or 1) / 5)
        return bonus
