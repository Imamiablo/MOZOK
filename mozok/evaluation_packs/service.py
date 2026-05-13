from __future__ import annotations

from sqlalchemy.orm import Session

from mozok.action_planning.schemas import ActionPlanRequest
from mozok.action_planning.service import ActionPlanningService
from mozok.agent.service import AgentService
from mozok.context.context_builder import ContextBuilder
from mozok.core.bot_core import get_memory_service
from mozok.evaluation_packs.schemas import (
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationCheckResult,
    EvaluationPackRunRequest,
    EvaluationPackRunResponse,
)


def _contains(haystack: str, needle: str) -> bool:
    return str(needle or "").lower() in str(haystack or "").lower()


class EvaluationPackService:
    """Scenario/cognition/action regression checks without calling an LLM."""

    def __init__(self, db: Session):
        self.db = db
        self.memory_service = get_memory_service(db)

    def run(self, request: EvaluationPackRunRequest) -> EvaluationPackRunResponse:
        results = [self._run_case(case) for case in request.cases]
        failed = [item for item in results if not item.passed]
        return EvaluationPackRunResponse(
            pack_name=request.pack_name,
            read_only=True,
            passed=not failed,
            case_count=len(results),
            failed_count=len(failed),
            results=results,
            notes=[
                "Evaluation Packs V2 checks context, cognitive broadcast, perception, and action intents without calling the LLM.",
                "Use this for regression packs before manually testing free-form chat behaviour.",
            ],
        )

    def _run_case(self, case: EvaluationCase) -> EvaluationCaseResult:
        agent = AgentService(self.db).get_or_create_default_agent(case.agent_id)
        context = ContextBuilder(db=self.db, memory_service=self.memory_service).build(
            agent=agent,
            user_message=case.message,
            session_id=f"eval:{case.case_id}",
            short_term_limit=0,
            update_memory_access=False,
            enforce_token_budget=True,
            agent_mode=case.agent_mode,
            enable_cognitive_field=case.enable_cognitive_field,
            sensory_inputs=case.sensory_inputs,
            perception_events=case.perception_events,
            perception_profile=case.perception_profile,
            attention_focus_keywords=case.attention_focus_keywords,
            include_goals=True,
            goal_limit=10,
            include_procedural_skills=True,
            procedural_skill_limit=10,
            select_relevant_procedural_skills=True,
            procedural_skill_fallback_to_priority=True,
            include_shared_procedural_skills=True,
            include_knowledge_relations=True,
            include_related_knowledge_relations=True,
            knowledge_relation_traversal_depth=2,
            related_knowledge_relation_limit=20,
            world_id=case.world_id,
            lorebook_limit=10,
            include_entity_states=True,
            entity_state_limit=10,
        )
        prompt = context.to_system_prompt()
        cognitive_dump = context.cognitive_field.model_dump(mode="json") if context.cognitive_field else None
        action_plan = ActionPlanningService(self.db).plan(
            case.agent_id,
            ActionPlanRequest(
                user_message=case.message,
                agent_mode=case.agent_mode,
                cognitive_field=cognitive_dump,
                sensory_inputs=[item.model_dump(mode="json") for item in case.sensory_inputs],
                available_tools=case.available_tools,
            ),
        )
        selected_action = action_plan.selected_action
        checks: list[EvaluationCheckResult] = []
        exp = case.expectations

        for needle in exp.prompt_contains:
            checks.append(EvaluationCheckResult(name="prompt_contains", passed=_contains(prompt, needle), detail=needle))
        for needle in exp.prompt_not_contains:
            checks.append(EvaluationCheckResult(name="prompt_not_contains", passed=not _contains(prompt, needle), detail=needle))
        if exp.cognitive_winner_contains is not None:
            label = ""
            if cognitive_dump:
                label = str((cognitive_dump.get("broadcast") or {}).get("selected_label") or cognitive_dump.get("winning_thought_id") or "")
            checks.append(EvaluationCheckResult(name="cognitive_winner_contains", passed=_contains(label, exp.cognitive_winner_contains), detail=label))
        if exp.expected_min_candidates is not None:
            count = int(cognitive_dump.get("candidate_count") or 0) if cognitive_dump else 0
            checks.append(EvaluationCheckResult(name="expected_min_candidates", passed=count >= exp.expected_min_candidates, detail=str(count)))
        if exp.expected_action_kind is not None:
            got = selected_action.action_kind if selected_action else None
            checks.append(EvaluationCheckResult(name="expected_action_kind", passed=got == exp.expected_action_kind, detail=str(got)))
        if exp.expected_action_tool is not None:
            got = selected_action.tool_name if selected_action else None
            checks.append(EvaluationCheckResult(name="expected_action_tool", passed=got == exp.expected_action_tool, detail=str(got)))
        if exp.expected_perception_channels_any:
            channels = set(context.perception_report.channels if context.perception_report else [])
            wanted = set(exp.expected_perception_channels_any)
            checks.append(EvaluationCheckResult(name="expected_perception_channels_any", passed=bool(channels & wanted), detail=", ".join(sorted(channels))))

        passed = all(check.passed for check in checks) if checks else True
        return EvaluationCaseResult(
            case_id=case.case_id,
            agent_id=case.agent_id,
            passed=passed,
            checks=checks,
            cognitive_winner=(cognitive_dump or {}).get("winning_thought_id") if cognitive_dump else None,
            selected_action_kind=selected_action.action_kind if selected_action else None,
            selected_action_tool=selected_action.tool_name if selected_action else None,
            prompt_preview=prompt[:2000],
        )
