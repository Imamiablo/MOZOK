from __future__ import annotations

from typing import Any

from mozok_game.engine.models import Agent
from mozok_game.engine.world_state import WorldState


def update_cognitive_trace(world: WorldState, agent: Agent, tool_name: str, rationale: str = "") -> None:
    """Create a readable local cognitive-field trace for the demo HUD.

    Live MOZOK API mode can overwrite these fields with real runtime tick data.
    Offline mode uses this deterministic trace so the player still sees why an
    agent appears to care about something.
    """

    tags = _recent_tags(world)
    urgent, urgent_value = agent.needs.most_urgent
    memory = _pick_memory(agent, tags)

    if "cave" in tags and agent.id == "alice":
        focus = "Cave signal is competing for attention."
        score = 0.91
        risk = "mystery"
    elif "food" in tags and agent.id == "boris":
        focus = "Supply trust is under pressure."
        score = 0.88
        risk = "social"
    elif "danger" in tags and agent.id == "mira":
        focus = "Group safety feels fragile."
        score = 0.86
        risk = "high"
    else:
        focus = f"{urgent} need is most salient."
        score = min(0.95, 0.35 + urgent_value / 130.0)
        risk = "low" if urgent_value < 65 else "medium"

    agent.brain_focus = focus
    agent.brain_focus_score = score
    agent.brain_memory = memory
    agent.brain_risk = risk
    agent.brain_broadcast = _broadcast_line(agent, focus, tool_name, rationale, memory)

    if memory and _should_flash(world, agent, memory):
        world.flash(
            agent.id,
            "Memory resonance",
            memory,
            kind="memory",
            intensity=max(0.45, min(1.0, score)),
        )


def apply_api_cognitive_trace(agent: Agent, data: dict[str, Any]) -> None:
    cognitive = data.get("cognitive_field") or {}
    broadcast = cognitive.get("broadcast") or {}
    self_model = data.get("self_model") or {}
    state = self_model.get("state") or {}

    selected_label = broadcast.get("selected_label") or broadcast.get("summary") or state.get("active_focus")
    if selected_label:
        agent.brain_focus = str(selected_label)
    if cognitive.get("winning_score") is not None:
        agent.brain_focus_score = float(cognitive.get("winning_score") or 0.0)
    if broadcast.get("working_memory_line"):
        agent.brain_memory = str(broadcast["working_memory_line"])
    if state.get("limitations"):
        agent.brain_risk = str(state["limitations"][0])[:64]
    elif state.get("uncertainty") is not None:
        agent.brain_risk = f"uncertainty {float(state['uncertainty']):.2f}"
    if broadcast.get("summary"):
        agent.brain_broadcast = str(broadcast["summary"])


def build_dialogue_options(world: WorldState, agent: Agent) -> list[dict[str, str]]:
    options = [
        {"id": "memory", "label": "Ask what they remember"},
        {"id": "intent", "label": "Ask what they plan"},
    ]
    tags = _recent_tags(world)
    if agent.id == "boris" and "food" in tags:
        options.append({"id": "challenge", "label": "Challenge him about supplies"})
    elif agent.emotion in {"afraid", "tired"} or agent.needs.stress > 50:
        options.append({"id": "reassure", "label": "Reassure them"})
    else:
        options.append({"id": "probe", "label": "Press for a theory"})
    return options


def apply_dialogue_choice(world: WorldState, agent: Agent, choice_id: str) -> str:
    tags = _recent_tags(world)
    if choice_id == "memory":
        memory = _pick_memory(agent, tags) or (agent.memory_snippets[0] if agent.memory_snippets else "Nothing clear. Just the shape of the night.")
        line = f"{agent.name}: {memory}"
        world.flash(agent.id, "Memory surfaced", memory, kind="memory", intensity=0.82)
    elif choice_id == "intent":
        line = f"{agent.name}: I am focused on this: {agent.brain_focus} Next move: {agent.last_action}."
        world.flash(agent.id, "Conscious broadcast", agent.brain_broadcast, kind="focus", intensity=max(0.45, agent.brain_focus_score))
    elif choice_id == "challenge":
        agent.social_to_player.trust -= 3.0
        agent.social_to_player.resentment += 8.0
        agent.social_to_player.clamp()
        line = f"{agent.name}: Because someone has to count. Hunger turns nice people into thieves."
        world.flash(agent.id, "Belief reinforced", "Supplies are social trust made physical.", kind="belief", intensity=0.78)
    elif choice_id == "reassure":
        agent.social_to_player.trust += 5.0
        agent.social_to_player.fear = max(0.0, agent.social_to_player.fear - 4.0)
        agent.needs.stress = max(0.0, agent.needs.stress - 8.0)
        agent.social_to_player.clamp()
        line = f"{agent.name}: Good. Say that again if I start spiralling."
        world.flash(agent.id, "State update", "Player reassurance lowered stress and raised trust.", kind="state", intensity=0.65)
    else:
        theory = _theory_for(agent)
        line = f"{agent.name}: {theory}"
        world.flash(agent.id, "Hypothesis", theory, kind="belief", intensity=0.7)

    agent.last_dialogue = line
    world.log(
        "player_dialogue_choice",
        line,
        source=agent.id,
        salience=7,
        tags=["dialogue", "social", "choice"],
        metadata={"agent_id": agent.id, "choice_id": choice_id},
    )
    return line


def trigger_scripted_moment(world: WorldState, moment_id: str) -> None:
    if moment_id == "food_taken":
        boris = world.agents.get("boris")
        crate = world.objects.get("food_crate_01")
        if not boris:
            return
        boris.social_to_player.resentment += 7.0
        boris.social_to_player.trust -= 2.0
        boris.social_to_player.clamp()
        food_left = int((crate.state or {}).get("food", 0)) if crate else 0
        if "food_taken_boris_flash" not in world.scripted_flags:
            world.scripted_flags.add("food_taken_boris_flash")
            world.flash("boris", "Memory check", "Boris counted four rations before dusk.", kind="memory", intensity=0.9)
            world.log(
                "scripted_boris_supply_warning",
                "Boris looks at the crate, then at your hands. He says nothing yet.",
                source="boris",
                salience=8,
                tags=["agent", "food", "conflict", "memory"],
                metadata={"agent_id": "boris"},
            )
        elif food_left <= 1:
            world.flash("boris", "Social risk", "The ration count is close to becoming an accusation.", kind="risk", intensity=0.86)
        return

    if moment_id == "cave_inspected" and "cave_first_click" not in world.scripted_flags:
        world.scripted_flags.add("cave_first_click")
        alice = world.agents.get("alice")
        mira = world.agents.get("mira")
        if alice:
            alice.needs.curiosity += 12.0
            alice.needs.stress += 4.0
            alice.needs.clamp()
            world.flash("alice", "Memory resonance", "The cave clicked after sunset. Now it answered again.", kind="memory", intensity=0.95)
            world.log(
                "scripted_alice_cave_theory",
                "Alice whispers: It is responding to attention, not time.",
                source="alice",
                salience=9,
                tags=["agent", "cave", "dialogue", "mystery"],
                metadata={"agent_id": "alice"},
            )
        if mira:
            mira.needs.stress += 10.0
            mira.needs.clamp()
            world.flash("mira", "Threat model", "Unknown cave signal raises group-safety risk.", kind="risk", intensity=0.82)
        return

    if moment_id == "radio_inspected" and "radio_first_signal" not in world.scripted_flags:
        world.scripted_flags.add("radio_first_signal")
        world.log(
            "scripted_radio_signal",
            "The radio exhales static. For half a second, every agent hears their own name.",
            source="radio_01",
            salience=10,
            tags=["radio", "mystery", "sound", "agent"],
        )
        for agent in world.agents.values():
            agent.needs.stress += 5.0
            agent.needs.curiosity += 5.0
            agent.needs.clamp()
            world.flash(agent.id, "Sensory spike", "The radio signal felt personally addressed.", kind="perception", intensity=0.8)


def run_social_director(world: WorldState) -> None:
    if world.turn - world.last_agent_conversation_turn < 2:
        return
    pairs = _nearby_pairs(world)
    if not pairs:
        return

    tags = _recent_tags(world)
    speaker, listener = _choose_pair(pairs, tags)
    if not speaker or not listener:
        return

    line = _agent_to_agent_line(speaker, listener, tags)
    speaker.last_dialogue = f"{speaker.name}: {line}"
    world.last_agent_conversation_turn = world.turn
    world.log(
        "agent_agent_dialogue",
        f"{speaker.name} to {listener.name}: {line}",
        source=speaker.id,
        salience=6,
        tags=["dialogue", "agent", "social"],
        metadata={"speaker_id": speaker.id, "listener_id": listener.id},
    )
    world.flash(listener.id, "Social attention", f"{speaker.name} redirected {listener.name}'s focus.", kind="social", intensity=0.58)


def _recent_tags(world: WorldState) -> set[str]:
    return {tag for event in world.event_log[-10:] for tag in event.tags}


def _pick_memory(agent: Agent, tags: set[str]) -> str:
    if not agent.memory_snippets:
        return ""
    if "cave" in tags:
        for memory in agent.memory_snippets:
            if "cave" in memory.lower() or "click" in memory.lower():
                return memory
    if "food" in tags:
        for memory in agent.memory_snippets:
            if "ration" in memory.lower() or "supplies" in memory.lower() or "crate" in memory.lower():
                return memory
    if "water" in tags:
        for memory in agent.memory_snippets:
            if "spring" in memory.lower() or "footprints" in memory.lower():
                return memory
    return agent.memory_snippets[0]


def _broadcast_line(agent: Agent, focus: str, tool_name: str, rationale: str, memory: str) -> str:
    memory_part = memory if memory else "no strong memory resonance"
    rationale_part = rationale.replace("OFFLINE: ", "") if rationale else "local director trace"
    return f"{focus} Memory: {memory_part} Action: {tool_name}. Reason: {rationale_part}"


def _should_flash(world: WorldState, agent: Agent, memory: str) -> bool:
    recent = [flash for flash in world.brain_flashes[-5:] if flash.agent_id == agent.id]
    return all(flash.content != memory for flash in recent)


def _nearby_pairs(world: WorldState) -> list[tuple[Agent, Agent]]:
    agents = [agent for agent in world.agents.values() if agent.alive]
    pairs: list[tuple[Agent, Agent]] = []
    for left in agents:
        for right in agents:
            if left.id >= right.id:
                continue
            if left.position.manhattan(right.position) <= 3:
                pairs.append((left, right))
    return pairs


def _choose_pair(pairs: list[tuple[Agent, Agent]], tags: set[str]) -> tuple[Agent | None, Agent | None]:
    for left, right in pairs:
        ids = {left.id, right.id}
        if "food" in tags and "boris" in ids:
            return (left, right) if left.id == "boris" else (right, left)
        if "cave" in tags and "alice" in ids:
            return (left, right) if left.id == "alice" else (right, left)
        if "danger" in tags and "mira" in ids:
            return (left, right) if left.id == "mira" else (right, left)
    return pairs[0] if pairs else (None, None)


def _agent_to_agent_line(speaker: Agent, listener: Agent, tags: set[str]) -> str:
    if speaker.id == "boris" and "food" in tags:
        return "Nobody touches the crate without saying it out loud first."
    if speaker.id == "alice" and "cave" in tags:
        return "If the cave responds to us, then it is part of the conversation."
    if speaker.id == "mira" and ("danger" in tags or "sound" in tags):
        return "Closer to the fire. I am not treating panic in the dark."
    urgent, value = speaker.needs.most_urgent
    return f"I cannot ignore {urgent} much longer. It is at {value:.0f}."


def _theory_for(agent: Agent) -> str:
    if agent.id == "alice":
        return "The island feels designed. Not haunted. Designed."
    if agent.id == "boris":
        return "The first real monster here will be bad accounting."
    if agent.id == "mira":
        return "The island is pushing us apart. That is how people get hurt."
    return "Something here is arranging pressure on purpose."
