from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from mozok.action_planning.schemas import ActionPlanRequest
from mozok.action_planning.service import ActionPlanningService
from mozok.agent.service import AgentService
from mozok.change_proposals.schemas import ChangeOperation, ChangeProposalAutoPolicyRequest, ChangeProposalCreate
from mozok.change_proposals.service import ChangeProposalService
from mozok.context.context_builder import ContextBuilder
from mozok.core.bot_core import get_memory_service
from mozok.perception.schemas import PerceptionEvent
from mozok.runtime_tick.schemas import AgentRuntimeBatchTickRequest, AgentRuntimeBatchTickResponse, AgentRuntimeTickHistoryEntry, AgentRuntimeTickHistoryResponse, AgentRuntimeTickRequest, AgentRuntimeTickResponse
from mozok.self_model.schemas import SelfModelRequest
from mozok.self_model.service import SelfModelService
from mozok.world_events.schemas import WorldEventToPerceptionRequest
from mozok.world_events.service import WorldEventService


class AgentRuntimeTickService:
    """One adapter-neutral autonomous-ish agent step.

    The MVP deliberately plans and proposes. It does not call an LLM, execute
    tools, move game objects, or write long-term memory unless proposal storage
    is explicitly requested.
    """

    def __init__(self, db: Session):
        self.db = db
        self.memory_service = get_memory_service(db)

    def batch_tick(self, request: AgentRuntimeBatchTickRequest) -> AgentRuntimeBatchTickResponse:
        ticks = []
        errors = []
        for agent_id in request.agent_ids:
            tick_request = request.tick_request_overrides.get(agent_id) or request.default_request.model_copy(deep=True)
            tick_request.world_id = request.world_id or tick_request.world_id
            if request.shared_message and not tick_request.message:
                tick_request.message = request.shared_message
            try:
                ticks.append(self.tick(agent_id, tick_request))
            except Exception as exc:  # pragma: no cover - defensive batch boundary
                errors.append({"agent_id": agent_id, "error": str(exc)})
                if request.stop_on_error:
                    break
        return AgentRuntimeBatchTickResponse(
            world_id=request.world_id,
            requested_count=len(request.agent_ids),
            completed_count=len(ticks),
            failed_count=len(errors),
            ticks=ticks,
            errors=errors,
        )

    def history(self, agent_id: str, limit: int = 20) -> AgentRuntimeTickHistoryResponse:
        agent = AgentService(self.db).get_or_create_default_agent(agent_id)
        metadata = dict(agent.metadata_json or {})
        entries = list(((metadata.get("runtime_tick") or {}).get("history") or []))
        parsed = [AgentRuntimeTickHistoryEntry.model_validate(item) for item in reversed(entries[-limit:])]
        return AgentRuntimeTickHistoryResponse(agent_id=agent_id, count=len(parsed), history=parsed)

    def tick(self, agent_id: str, request: AgentRuntimeTickRequest) -> AgentRuntimeTickResponse:
        agent = AgentService(self.db).get_or_create_default_agent(agent_id)
        tick_id = f"tick_{uuid4().hex[:16]}"
        message = request.message or "Runtime tick: evaluate current world events, goals, and possible next action."

        pulled_events = []
        perception_events: list[PerceptionEvent] = list(request.perception_events or [])
        if request.pull_world_events and request.world_event_limit > 0:
            response = WorldEventService(self.db).to_perception_events(
                WorldEventToPerceptionRequest(
                    world_id=request.world_id,
                    agent_id=agent_id,
                    limit=request.world_event_limit,
                    message=message,
                )
            )
            pulled_events = response.events
            perception_events.extend(response.perception_events)

        context = ContextBuilder(db=self.db, memory_service=self.memory_service).build(
            agent=agent,
            user_message=message,
            session_id=request.session_id,
            short_term_limit=0,
            update_memory_access=False,
            enforce_token_budget=True,
            agent_mode=request.agent_mode,
            apply_agent_mode_defaults=True,
            enable_cognitive_field=request.enable_cognitive_field,
            sensory_inputs=request.sensory_inputs,
            perception_events=perception_events,
            perception_profile=request.perception_profile,
            attention_focus_keywords=request.attention_focus_keywords,
            include_goals=request.include_goals,
            goal_limit=10,
            include_procedural_skills=request.include_procedural_skills,
            procedural_skill_limit=10,
            select_relevant_procedural_skills=True,
            procedural_skill_fallback_to_priority=True,
            include_shared_procedural_skills=True,
            include_knowledge_relations=request.include_knowledge_relations,
            include_related_knowledge_relations=request.include_related_knowledge_relations,
            knowledge_relation_traversal_depth=2,
            related_knowledge_relation_limit=20,
            world_id=request.world_id,
            lorebook_limit=10,
            include_entity_states=request.include_entity_states,
            entity_state_limit=10,
        )

        cognitive_dump = context.cognitive_field.model_dump(mode="json") if context.cognitive_field else None
        perception_summary = ""
        if context.perception_report:
            perception_summary = f"{context.perception_report.output_sensory_input_count} attended sensory input(s): {', '.join(context.perception_report.channels)}"

        self_model = SelfModelService(self.db).preview(
            agent_id,
            SelfModelRequest(
                agent_mode=request.agent_mode,
                current_task=message,
                user_message=message,
                cognitive_field=cognitive_dump,
                perception_summary=perception_summary,
                metadata={"tick_id": tick_id, **request.metadata},
            ),
        )

        attended_inputs = []
        if context.perception_report:
            # The report is summary-only; pass original sensory/perception content to action planner.
            attended_inputs = [item.model_dump(mode="json") for item in request.sensory_inputs]
            attended_inputs.extend(event.model_dump(mode="json") for event in perception_events[:12])

        action_plan = ActionPlanningService(self.db).plan(
            agent_id,
            ActionPlanRequest(
                user_message=message,
                agent_mode=request.agent_mode,
                cognitive_field=cognitive_dump,
                self_model=self_model.state.model_dump(mode="json"),
                sensory_inputs=attended_inputs,
                available_tools=request.available_tools,
                metadata={"tick_id": tick_id, **request.metadata},
            ),
        )

        proposals = []
        if request.create_change_proposals:
            proposal = ChangeProposalCreate(
                proposal_type="runtime_tick",
                summary=f"Review runtime tick {tick_id}",
                rationale="Runtime tick produced a cognitive focus, self-model preview, and action intent. Review before storing/executing downstream effects.",
                risk_level="low" if not action_plan.selected_action or action_plan.selected_action.risk_level == "low" else "medium",
                approval_mode=request.approval_mode,
                source="runtime_tick",
                store=request.store_proposals,
                metadata={
                    "tick_id": tick_id,
                    "selected_action_id": action_plan.selected_action_id,
                    "winning_thought_id": cognitive_dump.get("winning_thought_id") if cognitive_dump else None,
                },
                operations=[
                    ChangeOperation(
                        operation_type="update_agent_metadata",
                        target_type="agent",
                        summary="Store last runtime tick summary",
                        risk_level="low",
                        payload={
                            "metadata_patch": {
                                "runtime_tick": {
                                    "last_tick_id": tick_id,
                                    "last_selected_action": action_plan.selected_action.model_dump(mode="json") if action_plan.selected_action else None,
                                    "last_cognitive_winner": cognitive_dump.get("winning_thought_id") if cognitive_dump else None,
                                }
                            }
                        },
                    )
                ],
            )
            proposals.append(ChangeProposalService(self.db, self.memory_service).create(agent_id, proposal).model_dump(mode="json"))

        auto_apply_result = None
        if request.auto_apply:
            auto_apply_result = ChangeProposalService(self.db, self.memory_service).auto_apply(
                agent_id,
                ChangeProposalAutoPolicyRequest(approval_mode="apply_low_risk", proposal_type="runtime_tick", dry_run=not request.store_proposals),
            ).model_dump(mode="json")

        self._store_tick_history(
            agent=agent,
            tick_id=tick_id,
            world_id=request.world_id,
            message=message,
            cognitive_dump=cognitive_dump,
            action_plan=action_plan,
            proposal_count=len(proposals),
            metadata={"pulled_world_event_count": len(pulled_events), **request.metadata},
        )

        return AgentRuntimeTickResponse(
            agent_id=agent_id,
            world_id=request.world_id,
            read_only=not request.store_proposals and not request.auto_apply,
            tick_id=tick_id,
            context_debug=context.to_debug_dict(include_full_prompt=False, prompt_preview_chars=3000),
            pulled_world_events=pulled_events,
            cognitive_field=cognitive_dump,
            self_model=self_model,
            action_plan=action_plan,
            proposals=proposals,
            auto_apply_result=auto_apply_result,
            notes=[
                "Runtime Tick MVP plans/proposes only; external adapters execute world/tool actions.",
                "Use store_proposals=true only when you want reviewable tick summaries saved to agent metadata.",
            ],
        )


    def _store_tick_history(self, agent, tick_id: str, world_id: str, message: str, cognitive_dump, action_plan, proposal_count: int, metadata: dict):
        agent_metadata = dict(agent.metadata_json or {})
        bucket = dict(agent_metadata.get("runtime_tick") or {})
        history = list(bucket.get("history") or [])
        selected = action_plan.selected_action if action_plan else None
        history.append(
            {
                "tick_id": tick_id,
                "world_id": world_id,
                "message": message,
                "selected_action_id": action_plan.selected_action_id if action_plan else None,
                "selected_action_label": selected.label if selected else None,
                "cognitive_winner": cognitive_dump.get("winning_thought_id") if cognitive_dump else None,
                "proposal_count": proposal_count,
                "metadata": metadata or {},
            }
        )
        bucket["history"] = history[-100:]
        bucket["last_tick_id"] = tick_id
        agent_metadata["runtime_tick"] = bucket
        agent.metadata_json = agent_metadata
        self.db.add(agent)
        self.db.commit()
