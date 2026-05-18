from __future__ import annotations

from dataclasses import dataclass

from mozok_game.engine.models import Agent, Emotion
from mozok_game.engine.needs import update_emotion
from mozok_game.engine.relationships import format_relationship_delta, relationship_delta, relationship_snapshot
from mozok_game.engine.speech_actions import AgentDecision, ParsedSpeech
from mozok_game.engine.world_state import WorldState


POSITIVE_TONES = {"friendly", "kind", "supportive", "reassuring", "apologetic", "grateful", "warm"}
NEGATIVE_TONES = {"hostile", "threatening", "aggressive", "cruel", "insulting", "sexual", "coercive"}
UNCERTAIN_TONES = {"anxious", "fearful", "worried", "uncertain", "suspicious"}


@dataclass(slots=True)
class DialogueReaction:
    agent_id: str
    agent_name: str
    emotion: Emotion
    delta: dict[str, float]
    summary: str


def snapshot_player_relationship(agent: Agent) -> dict[str, float]:
    return relationship_snapshot(agent, "player")


def apply_open_dialogue_reaction(world: WorldState, agent: Agent, parsed: ParsedSpeech) -> None:
    """Apply small, semantic social ripples for ordinary player speech.

    Actionable accept/refuse/threat decisions already carry their own larger
    consequences. This function handles the otherwise invisible "I heard you"
    reaction after every sentence.
    """

    tone = parsed.tone.lower()
    acts = {act.kind for act in parsed.acts}
    actions = {act.action for act in parsed.acts}
    agent.needs.social = max(0.0, agent.needs.social - 4.0)
    if tone in POSITIVE_TONES:
        agent.social_to_player.trust += 1.1
        agent.social_to_player.affinity += 1.4
        agent.social_to_player.fear = max(0.0, agent.social_to_player.fear - 0.7)
        agent.needs.stress = max(0.0, agent.needs.stress - 1.2)
    elif tone in NEGATIVE_TONES or acts & {"threat", "hostile", "intimidation"} or "hostile" in actions:
        agent.social_to_player.trust -= 2.0
        agent.social_to_player.fear += 2.3
        agent.social_to_player.resentment += 2.4
        agent.needs.stress += 2.2
    elif tone in UNCERTAIN_TONES or parsed.claims:
        agent.needs.curiosity += 1.2
        agent.needs.stress += 0.7
    elif any(act.force == "order" or act.kind == "order" for act in parsed.acts):
        agent.social_to_player.resentment += 1.1 + agent.traits.get("dominance", 0.0)
        agent.social_to_player.trust -= 0.4
    else:
        agent.social_to_player.affinity += 0.25
    agent.needs.clamp()
    agent.social_to_player.clamp()


def finalise_dialogue_reaction(world: WorldState, agent: Agent, before: dict[str, float], parsed: ParsedSpeech, decision: AgentDecision | None = None) -> DialogueReaction:
    _set_phrase_emotion(agent, parsed, relationship_delta(before, agent, "player"), decision)
    delta = relationship_delta(before, agent, "player")
    summary = f"{agent.name}: {format_relationship_delta(delta)}; emotion {agent.emotion}"
    world.log(
        "dialogue_social_feedback",
        summary,
        source=agent.id,
        salience=4,
        tags=["dialogue", "social", "feedback"],
        metadata={"agent_id": agent.id, "delta": delta, "emotion": agent.emotion},
        actor_id=agent.id,
        target_id="player",
        visibility="private",
    )
    return DialogueReaction(agent.id, agent.name, agent.emotion, delta, summary)


def _set_phrase_emotion(agent: Agent, parsed: ParsedSpeech, delta: dict[str, float], decision: AgentDecision | None) -> None:
    update_emotion(agent)
    tone = parsed.tone.lower()
    if decision and decision.action == "hostile_alarm":
        agent.emotion = "angry" if agent.traits.get("dominance", 0.0) > agent.traits.get("anxiety", 0.0) else "afraid"
        agent.emotion_intensity = max(agent.emotion_intensity, 0.78)
        return
    if decision and decision.accepted and decision.action in {"follow_player", "go_to_object", "acknowledge_player_commitment"}:
        agent.emotion = "curious" if parsed.claims or decision.action == "go_to_object" else "neutral"
        agent.emotion_intensity = max(agent.emotion_intensity, 0.42)
        return
    if decision and decision.handled and not decision.accepted:
        agent.emotion = "suspicious"
        agent.emotion_intensity = max(agent.emotion_intensity, 0.5)
        return
    if tone in POSITIVE_TONES or delta.get("trust", 0.0) + delta.get("affinity", 0.0) > 1.2:
        agent.emotion = "happy"
        agent.emotion_intensity = max(agent.emotion_intensity, 0.45)
    elif tone in NEGATIVE_TONES or delta.get("resentment", 0.0) > 1.5:
        agent.emotion = "angry" if agent.social_to_player.fear < agent.social_to_player.resentment + 12 else "afraid"
        agent.emotion_intensity = max(agent.emotion_intensity, 0.62)
    elif parsed.claims or tone in UNCERTAIN_TONES:
        agent.emotion = "curious" if agent.traits.get("curiosity", 0.0) >= agent.traits.get("caution", 0.0) else "suspicious"
        agent.emotion_intensity = max(agent.emotion_intensity, 0.5)
    elif delta.get("trust", 0.0) < -0.2:
        agent.emotion = "suspicious"
        agent.emotion_intensity = max(agent.emotion_intensity, 0.48)
