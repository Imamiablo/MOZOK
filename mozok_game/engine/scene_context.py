from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from mozok_game.engine.appraisal import appraise_agent_beliefs
from mozok_game.engine.impulses import Impulse, generate_impulses
from mozok_game.engine.models import Agent
from mozok_game.engine.scene_validation import build_scene_grounding
from mozok_game.engine.world_state import WorldState


@dataclass(slots=True)
class SceneContext:
    speaker_id: str
    scenario_id: str
    hard_facts: list[str] = field(default_factory=list)
    pressure: dict[str, float] = field(default_factory=dict)
    beliefs: list[dict[str, Any]] = field(default_factory=list)
    visible_objects: list[dict[str, Any]] = field(default_factory=list)
    legal_interactions: list[dict[str, str]] = field(default_factory=list)
    appraisals: list[dict[str, Any]] = field(default_factory=list)
    candidate_impulses: list[dict[str, Any]] = field(default_factory=list)
    forbidden_mutations: list[str] = field(default_factory=list)

    def to_prompt_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_scene_context(world: WorldState, agent: Agent, candidate_impulses: list[Impulse] | None = None) -> SceneContext:
    grounding = build_scene_grounding(world, agent)
    appraisals = appraise_agent_beliefs(world, agent)
    impulses = candidate_impulses if candidate_impulses is not None else generate_impulses(world, agent, world.event_log[-10:])
    visible = []
    for item in grounding.nearby_objects:
        obj = world.objects.get(item["id"])
        visible.append(
            {
                **item,
                "tags": list(obj.tags) if obj else [],
                "aliases": list(obj.aliases) if obj else [],
                "state": dict(obj.state) if obj else {},
            }
        )
    return SceneContext(
        speaker_id=agent.id,
        scenario_id=world.scenario_id,
        hard_facts=[
            f"turn={world.turn}",
            f"speaker_position={agent.position.x},{agent.position.y}",
            f"player_position={world.player.position.x},{world.player.position.y}",
        ],
        pressure=dict(world.pressure),
        beliefs=[
            {
                "subject": belief.subject,
                "predicate": belief.predicate,
                "object": belief.object,
                "confidence": belief.confidence,
                "source": belief.source,
                "text": belief.text,
            }
            for belief in world.agent_beliefs
            if belief.agent_id == agent.id
        ][-8:],
        visible_objects=visible,
        legal_interactions=list(grounding.legal_interactions),
        appraisals=[item.to_dict() for item in appraisals[:6]],
        candidate_impulses=[
            {
                "kind": impulse.kind,
                "label": impulse.label,
                "score": impulse.score,
                "tool_name": impulse.tool_name,
                "parameters": dict(impulse.parameters),
                "reason": impulse.reason,
            }
            for impulse in impulses[:8]
        ],
        forbidden_mutations=[
            "Do not invent new objects, inventory, injuries, locations, or hidden truths.",
            "Physical actions must appear as requested actions and pass engine validation.",
            "Dialogue may describe feelings; item/object handling must match inventory, proximity, and legal interactions.",
        ],
    )
