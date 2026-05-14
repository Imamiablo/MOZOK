from __future__ import annotations

from mozok_game.engine.director import trigger_scripted_moment
from mozok_game.engine.models import Agent, WorldObject
from mozok_game.engine.world_state import WorldState


def interact_with_object(world: WorldState, obj: WorldObject) -> None:
    if obj.kind == "water_source":
        world.player.thirst = max(0.0, world.player.thirst - 40.0)
        world.log("player_drink", f"You drink from {obj.name}. The water is cold and almost sweet.", tags=["water", "survival"])
        return
    if obj.kind == "food_crate":
        amount = int(obj.state.get("food", 0))
        if amount > 0:
            obj.state["food"] = amount - 1
            world.player.inventory.append("ration")
            trigger_scripted_moment(world, "food_taken")
            world.log("player_take_food", f"You take one ration from {obj.name}. Food left: {obj.state['food']}.", tags=["food", "social_risk"])
        else:
            world.log("food_crate_empty", f"{obj.name} is empty. That will not make the camp calmer.", tags=["food", "conflict"])
        return
    if obj.kind == "campfire":
        obj.state["lit"] = True
        world.log("campfire_lit", "You feed the campfire. The shadows step back for a while.", tags=["safety", "camp"])
        for agent in world.agents.values():
            if agent.position.manhattan(obj.position) <= 3:
                agent.needs.stress = max(0.0, agent.needs.stress - 8.0)
        return
    if obj.kind == "cave_entrance":
        world.log("cave_inspected", "You peer into the cave. Something inside clicks twice, then goes silent.", salience=9, tags=["cave", "danger", "mystery"])
        for agent in world.agents.values():
            agent.needs.stress += 8.0
            agent.needs.curiosity += 10.0
            agent.needs.clamp()
        trigger_scripted_moment(world, "cave_inspected")
        return
    if obj.kind == "broken_radio":
        obj.state["inspected"] = True
        world.log("radio_inspected", "The radio is dead, but the battery compartment is warm.", salience=8, tags=["radio", "mystery"])
        trigger_scripted_moment(world, "radio_inspected")
        return
    world.log("object_inspected", f"You inspect {obj.name}. Nothing obvious happens.", tags=["inspect"])


def talk_to_agent(world: WorldState, agent: Agent) -> None:
    agent.needs.social = max(0.0, agent.needs.social - 15.0)
    agent.social_to_player.affinity += 2.0
    agent.social_to_player.trust += 1.0
    agent.social_to_player.clamp()
    recent_tags = {tag for event in world.event_log[-8:] for tag in event.tags}
    memory = agent.memory_snippets[0] if agent.memory_snippets else ""
    if agent.id == "boris" and ("food" in recent_tags or agent.social_to_player.resentment > 25):
        line = f"{agent.name}: I remember the crate count. Supplies are trust with a lid on it."
    elif agent.id == "alice" and ("cave" in recent_tags or agent.needs.curiosity > 65):
        line = f"{agent.name}: The cave keeps answering us in clicks. That is not geology."
    elif agent.id == "mira" and ("danger" in recent_tags or agent.needs.stress > 55):
        line = f"{agent.name}: Stay where I can see you. People vanish when groups pretend they are fine."
    elif agent.emotion == "afraid":
        line = f"{agent.name}: Please tell me you heard that too. I don't want to be the only one scared."
    elif agent.emotion == "angry":
        line = f"{agent.name}: We need rules. If everyone grabs supplies, this camp is finished."
    elif agent.emotion == "curious":
        line = f"{agent.name}: That cave is wrong. Not dangerous-wrong. Story-wrong. I need to know why."
    elif agent.emotion == "tired":
        line = f"{agent.name}: I can barely stand. If this island wants drama, it can wait until morning."
    elif memory:
        line = f"{agent.name}: I keep thinking about this: {memory}"
    else:
        line = f"{agent.name}: I'm still here. That's something, right?"
    agent.last_dialogue = line
    world.log("player_talk", line, source=agent.id, salience=6, tags=["dialogue", "social"], metadata={"agent_id": agent.id, "memory_hint": memory})
