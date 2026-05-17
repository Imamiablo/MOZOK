from __future__ import annotations

from mozok_game.engine.models import Agent, Emotion


def update_emotion(agent: Agent) -> None:
    needs = agent.needs
    social = agent.social_to_player
    emotion: Emotion = "neutral"
    intensity = 0.2
    if needs.stress > 75 or social.fear > 65:
        emotion, intensity = "afraid", max(needs.stress, social.fear) / 100.0
    elif social.resentment > 65:
        emotion, intensity = "angry", social.resentment / 100.0
    elif needs.fatigue > 80:
        emotion, intensity = "tired", needs.fatigue / 100.0
    elif needs.curiosity > 70:
        emotion, intensity = "curious", needs.curiosity / 100.0
    elif social.affinity > 70 and social.trust > 65:
        emotion, intensity = "happy", min(social.affinity, social.trust) / 100.0
    elif social.trust < 25:
        emotion, intensity = "suspicious", (100.0 - social.trust) / 100.0
    agent.emotion = emotion
    agent.emotion_intensity = max(0.1, min(1.0, intensity))


def apply_environment_needs(agent: Agent, near_safety: bool = False, near_danger: bool = False) -> None:
    agent.needs.tick()
    if near_safety:
        agent.needs.stress -= 2.0
        agent.needs.fatigue -= 1.0
    if near_danger:
        agent.needs.stress += 3.0
        agent.needs.curiosity += 2.0
    if "wounded" in agent.status_flags:
        agent.needs.fatigue += 1.2
        agent.needs.stress += 0.8
        if agent.needs.hunger > 85 or agent.needs.thirst > 85:
            agent.health = max(1.0, agent.health - 0.6)
    agent.needs.clamp()
    update_emotion(agent)
