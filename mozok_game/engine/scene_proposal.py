from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mozok_game.engine.capabilities import target_primitives
from mozok_game.engine.inventory import item_capabilities
from mozok_game.engine.models import Agent
from mozok_game.engine.scene_validation import validate_agent_dialogue
from mozok_game.engine.world_state import WorldState


@dataclass(slots=True)
class SceneDialogueLine:
    speaker_id: str
    text: str


@dataclass(slots=True)
class SceneRequestedAction:
    tool_name: str
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SceneClaim:
    text: str
    truth_status: str = "unverified"
    confidence: float = 0.0
    subject: str = ""
    predicate: str = ""
    object: str = ""
    target_object_id: str = ""


@dataclass(slots=True)
class SceneProposal:
    selected_impulse_id: str = ""
    dialogue: list[SceneDialogueLine] = field(default_factory=list)
    stage_directions: list[dict[str, Any]] = field(default_factory=list)
    requested_actions: list[SceneRequestedAction] = field(default_factory=list)
    claims: list[SceneClaim] = field(default_factory=list)
    rationale: str = ""


@dataclass(slots=True)
class SceneProposalValidationResult:
    text: str
    accepted_actions: list[SceneRequestedAction] = field(default_factory=list)
    rejected_actions: list[str] = field(default_factory=list)
    accepted_claims: list[SceneClaim] = field(default_factory=list)
    rewrites: list[str] = field(default_factory=list)
    rejected_physical_claims: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.rejected_actions and not self.rejected_physical_claims


def scene_proposal_from_dict(data: dict[str, Any], default_speaker_id: str = "") -> SceneProposal:
    dialogue: list[SceneDialogueLine] = []
    raw_dialogue = data.get("dialogue")
    if isinstance(raw_dialogue, str):
        dialogue.append(SceneDialogueLine(default_speaker_id, raw_dialogue))
    elif isinstance(raw_dialogue, list):
        for item in raw_dialogue:
            if isinstance(item, str):
                dialogue.append(SceneDialogueLine(default_speaker_id, item))
            elif isinstance(item, dict):
                dialogue.append(SceneDialogueLine(str(item.get("speaker_id") or default_speaker_id), str(item.get("text") or item.get("line") or "")))

    actions: list[SceneRequestedAction] = []
    for item in data.get("requested_actions") or []:
        if isinstance(item, dict):
            actions.append(SceneRequestedAction(str(item.get("tool_name") or item.get("tool") or item.get("action") or ""), dict(item.get("parameters") or item.get("params") or {})))

    claims: list[SceneClaim] = []
    for item in data.get("claims") or []:
        if isinstance(item, dict):
            claims.append(
                SceneClaim(
                    text=str(item.get("text") or ""),
                    truth_status=str(item.get("truth_status") or "unverified"),
                    confidence=float(item.get("confidence", 0.0) or 0.0),
                    subject=str(item.get("subject") or ""),
                    predicate=str(item.get("predicate") or ""),
                    object=str(item.get("object") or ""),
                    target_object_id=str(item.get("target_object_id") or ""),
                )
            )

    return SceneProposal(
        selected_impulse_id=str(data.get("selected_impulse_id") or data.get("impulse_id") or ""),
        dialogue=[line for line in dialogue if line.text],
        stage_directions=[dict(item) for item in data.get("stage_directions") or [] if isinstance(item, dict)],
        requested_actions=[action for action in actions if action.tool_name],
        claims=[claim for claim in claims if claim.text],
        rationale=str(data.get("rationale") or ""),
    )


def validate_scene_proposal(world: WorldState, agent: Agent, proposal: SceneProposal) -> SceneProposalValidationResult:
    text_parts: list[str] = []
    rewrites: list[str] = []
    rejected_physical: list[str] = []
    for line in proposal.dialogue:
        speaker = world.agents.get(line.speaker_id) or agent
        result = validate_agent_dialogue(world, speaker, line.text)
        text_parts.append(result.text)
        rewrites.extend(result.rewrites)
        rejected_physical.extend(result.rejected_physical_claims)

    accepted_actions: list[SceneRequestedAction] = []
    rejected_actions: list[str] = []
    for action in proposal.requested_actions:
        reason = _action_rejection_reason(world, agent, action)
        if reason:
            rejected_actions.append(f"{action.tool_name}: {reason}")
        else:
            accepted_actions.append(action)

    claims = [
        claim
        for claim in proposal.claims
        if claim.truth_status in {"unverified", "observed", "verified", "rumour", "subjective_observation"}
    ]
    return SceneProposalValidationResult(
        text="\n".join(part for part in text_parts if part),
        accepted_actions=accepted_actions,
        rejected_actions=rejected_actions,
        accepted_claims=claims,
        rewrites=rewrites,
        rejected_physical_claims=rejected_physical,
    )


def scene_proposal_prompt_contract() -> str:
    return (
        "Return structured JSON when possible: {dialogue:[{speaker_id,text}], stage_directions:[], "
        "requested_actions:[{tool_name,parameters}], claims:[{text,truth_status,confidence}], rationale}. "
        "Only requested_actions may imply physical world changes. Dialogue and stage directions must stay grounded."
    )


def _action_rejection_reason(world: WorldState, agent: Agent, action: SceneRequestedAction) -> str:
    params = action.parameters
    if action.tool_name in {"wait", "talk_to_player"}:
        return ""
    if action.tool_name == "move_to_object":
        return "" if str(params.get("object_id") or params.get("target_object_id")) in world.objects else "unknown target object"
    if action.tool_name == "talk_to_agent":
        target = world.agents.get(str(params.get("target_agent_id") or ""))
        if not target:
            return "unknown target agent"
        if agent.position.manhattan(target.position) > 4:
            return "target agent is too far away"
        return ""
    if action.tool_name == "interact_with_object":
        obj = world.objects.get(str(params.get("object_id") or params.get("target_object_id") or ""))
        interaction_id = str(params.get("interaction_id") or "")
        if not obj:
            return "unknown object"
        if agent.position.manhattan(obj.position) > 1:
            return "object is not adjacent"
        if interaction_id and interaction_id not in obj.interactions:
            return "object does not expose that interaction"
        return ""
    if action.tool_name == "use_item_on_target":
        item_id = str(params.get("item_id") or "")
        target_id = str(params.get("target_id") or params.get("target_object_id") or "")
        primitive = str(params.get("primitive") or "")
        obj = world.objects.get(target_id)
        if item_id not in agent.inventory:
            return "speaker does not have item"
        if not obj:
            return "unknown target"
        if primitive not in item_capabilities(item_id):
            return "item lacks primitive"
        if primitive not in target_primitives(obj):
            return "target does not accept primitive"
        return ""
    if action.tool_name == "give_item":
        item_id = str(params.get("item_id") or "")
        target = world.agents.get(str(params.get("target_agent_id") or ""))
        if item_id not in agent.inventory:
            return "speaker does not have item"
        if not target:
            return "unknown target agent"
        if agent.position.manhattan(target.position) > 2:
            return "target agent is too far away"
        return ""
    return "unsupported action in scene proposal"
