from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from sqlalchemy.orm import Session

from mozok.context.context_builder import ContextBuilder, ContextPackage
from mozok.db.models import AgentRecord
from mozok.memory.service import MemoryService


@dataclass(slots=True)
class ScenarioContextExpectations:
    """Expected properties of an assembled Mozok context.

    These checks are deliberately prompt-level and ID/key-level. They are meant
    to catch regressions that ordinary unit tests can miss, such as a restricted
    lore entry leaking into an NPC context or a procedural skill silently no
    longer being selected for a scenario turn.
    """

    required_text: list[str] = field(default_factory=list)
    forbidden_text: list[str] = field(default_factory=list)
    required_memory_text: list[str] = field(default_factory=list)
    forbidden_memory_text: list[str] = field(default_factory=list)
    required_lorebook_keys: list[str] = field(default_factory=list)
    forbidden_lorebook_keys: list[str] = field(default_factory=list)
    required_goal_keys: list[str] = field(default_factory=list)
    forbidden_goal_keys: list[str] = field(default_factory=list)
    required_procedural_skill_keys: list[str] = field(default_factory=list)
    forbidden_procedural_skill_keys: list[str] = field(default_factory=list)
    required_entity_ids: list[str] = field(default_factory=list)
    forbidden_entity_ids: list[str] = field(default_factory=list)
    min_counts: dict[str, int] = field(default_factory=dict)
    case_sensitive: bool = False


@dataclass(slots=True)
class ScenarioEvaluationCase:
    """One scenario-context regression case.

    ``build_options`` is passed directly to ``ContextBuilder.build``. This keeps
    the runner flexible enough for later budget-policy, graph-expansion, and
    narrator/assistant-specific checks without creating a new test helper for
    every feature.
    """

    name: str
    agent_id: str
    user_message: str
    world_id: str = "default"
    session_id: str = "scenario_eval"
    build_options: dict[str, Any] = field(default_factory=dict)
    expectations: ScenarioContextExpectations = field(default_factory=ScenarioContextExpectations)


@dataclass(slots=True)
class ScenarioEvaluationResult:
    name: str
    passed: bool
    errors: list[str]
    context: ContextPackage | None = None
    debug: dict[str, Any] = field(default_factory=dict)
    prompt: str = ""


def run_context_scenarios(
    *,
    db: Session,
    memory_service: MemoryService,
    cases: Iterable[ScenarioEvaluationCase],
) -> list[ScenarioEvaluationResult]:
    """Evaluate multiple scenario cases and return structured results."""

    return [
        evaluate_context_scenario(db=db, memory_service=memory_service, case=case)
        for case in cases
    ]


def evaluate_context_scenario(
    *,
    db: Session,
    memory_service: MemoryService,
    case: ScenarioEvaluationCase,
) -> ScenarioEvaluationResult:
    """Build one context package and compare it with expected scenario rules."""

    errors: list[str] = []
    agent = db.get(AgentRecord, case.agent_id)
    if agent is None:
        return ScenarioEvaluationResult(
            name=case.name,
            passed=False,
            errors=[f"Agent not found: {case.agent_id}"],
        )

    build_options = _default_build_options(case.world_id)
    build_options.update(case.build_options or {})

    context = ContextBuilder(db=db, memory_service=memory_service).build(
        agent=agent,
        user_message=case.user_message,
        session_id=case.session_id,
        **build_options,
    )
    prompt = context.to_system_prompt()
    debug = context.to_debug_dict(include_full_prompt=True)

    _check_text(
        errors,
        label="prompt",
        haystack=prompt,
        required=case.expectations.required_text,
        forbidden=case.expectations.forbidden_text,
        case_sensitive=case.expectations.case_sensitive,
    )
    _check_text(
        errors,
        label="memory context",
        haystack="\n".join(_memory_texts(context)),
        required=case.expectations.required_memory_text,
        forbidden=case.expectations.forbidden_memory_text,
        case_sensitive=case.expectations.case_sensitive,
    )
    _check_required_keys(errors, "lorebook", _lorebook_keys(context), case.expectations.required_lorebook_keys)
    _check_forbidden_keys(errors, "lorebook", _lorebook_keys(context), case.expectations.forbidden_lorebook_keys)
    _check_required_keys(errors, "goal", _goal_keys(context), case.expectations.required_goal_keys)
    _check_forbidden_keys(errors, "goal", _goal_keys(context), case.expectations.forbidden_goal_keys)
    _check_required_keys(
        errors,
        "procedural skill",
        _procedural_skill_keys(context),
        case.expectations.required_procedural_skill_keys,
    )
    _check_forbidden_keys(
        errors,
        "procedural skill",
        _procedural_skill_keys(context),
        case.expectations.forbidden_procedural_skill_keys,
    )
    _check_required_keys(errors, "entity state", _entity_ids(context), case.expectations.required_entity_ids)
    _check_forbidden_keys(errors, "entity state", _entity_ids(context), case.expectations.forbidden_entity_ids)
    _check_min_counts(errors, context, case.expectations.min_counts)

    return ScenarioEvaluationResult(
        name=case.name,
        passed=not errors,
        errors=errors,
        context=context,
        debug=debug,
        prompt=prompt,
    )


def _default_build_options(world_id: str) -> dict[str, Any]:
    return {
        "short_term_limit": 0,
        "core_limit": 5,
        "semantic_limit": 5,
        "episodic_limit": 5,
        "raw_limit": 0,
        "update_memory_access": False,
        "enforce_token_budget": False,
        "include_goals": True,
        "goal_limit": 10,
        "include_procedural_skills": True,
        "procedural_skill_limit": 10,
        "select_relevant_procedural_skills": True,
        "procedural_skill_min_score": 1.0,
        "procedural_skill_fallback_to_priority": False,
        "include_knowledge_relations": True,
        "knowledge_relation_limit": 10,
        "include_related_knowledge_relations": True,
        "related_knowledge_relation_limit": 10,
        "world_id": world_id,
        "lorebook_limit": 10,
        "include_public_lore": True,
        "include_narrator_only_lore": False,
        "include_entity_states": True,
        "entity_state_limit": 10,
    }


def _normalise(value: str, *, case_sensitive: bool) -> str:
    return value if case_sensitive else value.lower()


def _check_text(
    errors: list[str],
    *,
    label: str,
    haystack: str,
    required: list[str],
    forbidden: list[str],
    case_sensitive: bool,
) -> None:
    normalised_haystack = _normalise(haystack or "", case_sensitive=case_sensitive)
    for needle in required:
        if _normalise(needle, case_sensitive=case_sensitive) not in normalised_haystack:
            errors.append(f"Missing required {label} text: {needle!r}")
    for needle in forbidden:
        if _normalise(needle, case_sensitive=case_sensitive) in normalised_haystack:
            errors.append(f"Forbidden {label} text was present: {needle!r}")


def _check_required_keys(errors: list[str], label: str, actual: set[str], required: list[str]) -> None:
    for key in required:
        if key not in actual:
            errors.append(f"Missing required {label} key/id: {key!r}; actual={sorted(actual)!r}")


def _check_forbidden_keys(errors: list[str], label: str, actual: set[str], forbidden: list[str]) -> None:
    for key in forbidden:
        if key in actual:
            errors.append(f"Forbidden {label} key/id was present: {key!r}")


def _check_min_counts(errors: list[str], context: ContextPackage, min_counts: dict[str, int]) -> None:
    counts = {
        "memories": len(context.used_memory_ids()),
        "short_term": context.used_short_term_count(),
        "goals": len(context.goal_items),
        "procedural_skills": len(context.procedural_skill_items),
        "knowledge_relations": len(context.knowledge_relation_items),
        "lorebook": len(context.lorebook_items),
        "entity_states": len(context.entity_state_items),
    }
    for key, minimum in min_counts.items():
        if key not in counts:
            errors.append(f"Unknown min_count key {key!r}; supported={sorted(counts)!r}")
            continue
        if counts[key] < int(minimum):
            errors.append(f"Expected at least {minimum} {key}, got {counts[key]}")


def _memory_texts(context: ContextPackage) -> list[str]:
    memories = (
        list(context.core_memories)
        + list(context.semantic_memories)
        + list(context.episodic_memories)
        + list(context.raw_memories)
    )
    return [str(getattr(memory, "content", "")) for memory in memories]


def _lorebook_keys(context: ContextPackage) -> set[str]:
    return {item.entry_key for item in context.lorebook_items}


def _goal_keys(context: ContextPackage) -> set[str]:
    return {item.goal_key for item in context.goal_items}


def _procedural_skill_keys(context: ContextPackage) -> set[str]:
    return {item.skill_key for item in context.procedural_skill_items}


def _entity_ids(context: ContextPackage) -> set[str]:
    return {item.entity_id for item in context.entity_state_items}
