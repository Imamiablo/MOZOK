from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mozok_game.engine.models import Agent, AgentBelief
from mozok_game.engine.world_state import WorldState


@dataclass(slots=True)
class AgentAppraisal:
    agent_id: str
    concern: str
    score: float
    reason: str
    world_event_id: str = ""
    belief_text: str = ""
    pressure_axes: list[str] = field(default_factory=list)
    suggested_impulses: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "concern": self.concern,
            "score": round(self.score, 2),
            "reason": self.reason,
            "world_event_id": self.world_event_id,
            "belief_text": self.belief_text,
            "pressure_axes": list(self.pressure_axes),
            "suggested_impulses": list(self.suggested_impulses),
        }


def appraise_agent_beliefs(world: WorldState, agent: Agent, limit: int = 8) -> list[AgentAppraisal]:
    appraisals: list[AgentAppraisal] = []
    beliefs = [belief for belief in world.agent_beliefs if belief.agent_id == agent.id][-limit:]
    for belief in beliefs:
        appraisal = _appraise_belief(world, agent, belief)
        if appraisal and appraisal.score >= 18.0:
            appraisals.append(appraisal)
    appraisals.sort(key=lambda item: item.score, reverse=True)
    return appraisals[:limit]


def appraisal_bonus_for_impulse(appraisals: list[AgentAppraisal], impulse_kind: str, atom_id: str = "") -> tuple[float, str]:
    keys = {impulse_kind, atom_id}
    matched = [item for item in appraisals if keys.intersection(set(item.suggested_impulses))]
    if not matched:
        return 0.0, ""
    bonus = min(28.0, sum(item.score * 0.18 for item in matched))
    reasons = ", ".join(f"{item.concern}:{item.score:.0f}" for item in matched[:3])
    return bonus, f"appraisal bonus {bonus:.1f} from {reasons}"


def _appraise_belief(world: WorldState, agent: Agent, belief: AgentBelief) -> AgentAppraisal | None:
    for rule in _appraisal_rules(world):
        appraisal = _appraise_belief_with_rule(world, agent, belief, rule)
        if appraisal:
            return appraisal
    return None


def _appraisal_rules(world: WorldState) -> list[dict[str, Any]]:
    if world.appraisal_rules:
        return world.appraisal_rules
    path = Path(__file__).resolve().parents[1] / "data" / "appraisals" / "core_appraisals.json"
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [dict(item) for item in raw if isinstance(item, dict)] if isinstance(raw, list) else []


def _appraise_belief_with_rule(world: WorldState, agent: Agent, belief: AgentBelief, rule: dict[str, Any]) -> AgentAppraisal | None:
    tags = {tag.lower() for tag in belief.emotional_tags}
    text = f"{belief.subject} {belief.predicate} {belief.object} {belief.text}".lower()
    match_tags = {str(tag).lower() for tag in rule.get("match_tags") or []}
    match_text = [str(item).lower() for item in rule.get("match_text") or []]
    if match_tags and not match_tags.intersection(tags):
        if not any(item in text for item in match_text):
            return None
    elif match_text and not any(item in text for item in match_text):
        return None

    score = float(rule.get("base_score", 0.0))
    for trait, weight in dict(rule.get("trait_weights") or {}).items():
        score += agent.traits.get(str(trait), 0.0) * float(weight)
    for axis, weight in dict(rule.get("pressure_weights") or {}).items():
        score += world.pressure.get(str(axis), 0.0) * float(weight)
    score += _social_score(agent, dict(rule.get("social_weights") or {}))
    score += _hook_score(agent.values, rule.get("value_hooks"))
    score += _hook_score(agent.fears, rule.get("fear_hooks"))
    score *= 0.55 + max(0.0, min(1.0, belief.confidence)) * 0.45

    min_score = float(rule.get("min_score", 18.0))
    if score < min_score:
        return None
    return AgentAppraisal(
        agent_id=agent.id,
        concern=str(rule.get("concern") or rule.get("id") or "concern"),
        score=score,
        reason=str(rule.get("reason") or f"matched appraisal rule {rule.get('id', 'rule')}"),
        world_event_id=belief.world_event_id,
        belief_text=belief.text,
        pressure_axes=[str(axis) for axis in rule.get("pressure_axes") or []],
        suggested_impulses=[str(item) for item in rule.get("suggested_impulses") or []],
    )


def _social_score(agent: Agent, weights: dict[str, Any]) -> float:
    score = 0.0
    social = agent.social_to_player
    for key, weight in weights.items():
        amount = float(weight)
        if key == "low_trust":
            score += (100.0 - social.trust) * amount / 100.0 if amount > 1 else (100.0 - social.trust) * amount
        elif hasattr(social, str(key)):
            score += float(getattr(social, str(key))) * amount
    return score


def _hook_score(values: list[str], raw: Any) -> float:
    if isinstance(raw, dict):
        return sum(float(bonus) for hook, bonus in raw.items() if str(hook) in values)
    hooks = {str(item) for item in raw or []}
    return 12.0 if hooks.intersection(set(values)) else 0.0
