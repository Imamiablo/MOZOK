from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from mozok.action_planning.schemas import ActionToolSpec
from mozok.cognition.schemas import SensoryInput
from mozok.perception.schemas import PerceptionEvent, PerceptionProfile


class EvaluationExpectations(BaseModel):
    prompt_contains: list[str] = Field(default_factory=list)
    prompt_not_contains: list[str] = Field(default_factory=list)
    cognitive_winner_contains: str | None = None
    expected_action_kind: str | None = None
    expected_action_tool: str | None = None
    expected_min_candidates: int | None = None
    expected_perception_channels_any: list[str] = Field(default_factory=list)


class EvaluationCase(BaseModel):
    case_id: str
    agent_id: str
    message: str
    world_id: str = "default"
    agent_mode: str | None = None
    enable_cognitive_field: bool = True
    perception_events: list[PerceptionEvent] = Field(default_factory=list)
    sensory_inputs: list[SensoryInput] = Field(default_factory=list)
    perception_profile: PerceptionProfile | None = None
    attention_focus_keywords: list[str] = Field(default_factory=list)
    available_tools: list[ActionToolSpec] = Field(default_factory=list)
    expectations: EvaluationExpectations = Field(default_factory=EvaluationExpectations)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationPackRunRequest(BaseModel):
    pack_name: str = "adhoc"
    dry_run: bool = True
    cases: list[EvaluationCase] = Field(default_factory=list)


class EvaluationCheckResult(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class EvaluationCaseResult(BaseModel):
    case_id: str
    agent_id: str
    passed: bool
    checks: list[EvaluationCheckResult] = Field(default_factory=list)
    cognitive_winner: str | None = None
    selected_action_kind: str | None = None
    selected_action_tool: str | None = None
    prompt_preview: str = ""


class EvaluationPackRunResponse(BaseModel):
    pack_name: str
    read_only: bool = True
    passed: bool
    case_count: int = 0
    failed_count: int = 0
    results: list[EvaluationCaseResult] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
