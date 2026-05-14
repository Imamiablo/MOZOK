from __future__ import annotations

from mozok_game.engine.director import run_social_director, update_cognitive_trace
from mozok_game.engine.interactions import talk_to_agent
from mozok_game.engine.needs import apply_environment_needs, update_emotion
from mozok_game.engine.pathfinding import next_step_towards
from mozok_game.engine.world_state import WorldState
from mozok_game.mozok_client.client import BrainClient


def run_agent_ticks(world: WorldState, brain: BrainClient) -> None:
    recent = world.event_log[-10:]
    campfire = world.object_by_kind("campfire")
    cave = world.object_by_kind("cave_entrance")
    for agent in world.agents.values():
        if not agent.alive:
            continue
        near_campfire = bool(campfire and agent.position.manhattan(campfire.position) <= 2)
        near_cave = bool(cave and agent.position.manhattan(cave.position) <= 2)
        apply_environment_needs(agent, near_campfire=near_campfire, near_cave=near_cave)
        intent = brain.decide(world, agent, recent)
        apply_agent_intent(world, agent.id, intent.tool_name, intent.parameters, dialogue=intent.dialogue, rationale=intent.rationale)
        update_emotion(agent)
        if not intent.rationale.startswith("MOZOK API:"):
            update_cognitive_trace(world, agent, intent.tool_name, intent.rationale)
    run_social_director(world)
    world.turn += 1


def apply_agent_intent(world: WorldState, agent_id: str, tool_name: str, parameters: dict, dialogue: str = "", rationale: str = "") -> None:
    agent = world.agents[agent_id]
    agent.last_action = tool_name
    agent.last_rationale = rationale
    if tool_name == "talk_to_player" or (dialogue and agent.position.manhattan(world.player.position) <= 2):
        if dialogue:
            agent.last_dialogue = dialogue
            world.log("agent_dialogue", dialogue, source=agent.id, salience=6, tags=["dialogue", "agent"], metadata={"agent_id": agent.id, "rationale": rationale})
        else:
            talk_to_agent(world, agent)
        agent.needs.social = max(0.0, agent.needs.social - 12.0)
        return
    if tool_name == "move_to_object":
        object_id = parameters.get("object_id")
        obj = world.objects.get(object_id) if object_id else None
        if not obj:
            world.log("agent_wait", f"{agent.name} hesitates. They do not know where to go.", source=agent.id, tags=["agent", "wait"])
            return
        if agent.position.manhattan(obj.position) <= 1:
            _agent_use_object(world, agent_id, obj.id)
            return
        blocked = world.occupied_positions(exclude_agent_id=agent.id)
        step = next_step_towards(world.grid, agent.position, obj.position, blocked=blocked)
        if step:
            agent.position = step
            world.log("agent_move", f"{agent.name} moves towards {obj.name}. ({rationale})", source=agent.id, salience=4, tags=["agent", "movement"], metadata={"agent_id": agent.id, "target": obj.id})
        else:
            world.log("agent_blocked", f"{agent.name} wants to reach {obj.name}, but cannot find a path.", source=agent.id, tags=["agent", "blocked"])
        return
    world.log("agent_wait", f"{agent.name} waits, watching the camp. ({rationale})", source=agent.id, salience=3, tags=["agent", "wait"])


def _agent_use_object(world: WorldState, agent_id: str, object_id: str) -> None:
    agent = world.agents[agent_id]
    obj = world.objects[object_id]
    if obj.kind == "water_source":
        agent.needs.thirst = max(0.0, agent.needs.thirst - 45.0)
        world.log("agent_drink", f"{agent.name} drinks from {obj.name}.", source=agent.id, tags=["agent", "water"])
        return
    if obj.kind == "food_crate":
        amount = int(obj.state.get("food", 0))
        if amount > 0:
            obj.state["food"] = amount - 1
            agent.needs.hunger = max(0.0, agent.needs.hunger - 45.0)
            world.log("agent_eat", f"{agent.name} takes a ration. Food left: {obj.state['food']}.", source=agent.id, tags=["agent", "food"])
        else:
            agent.social_to_player.resentment += 4.0
            agent.social_to_player.clamp()
            world.log("agent_food_missing", f"{agent.name} checks {obj.name}. It is empty. Their face tightens.", source=agent.id, tags=["agent", "conflict", "food"])
        return
    if obj.kind in {"campfire", "shelter"}:
        agent.needs.fatigue = max(0.0, agent.needs.fatigue - 18.0)
        agent.needs.stress = max(0.0, agent.needs.stress - 12.0)
        world.log("agent_rest", f"{agent.name} rests near {obj.name}.", source=agent.id, tags=["agent", "rest"])
        return
    if obj.kind == "cave_entrance":
        agent.needs.stress += 10.0
        agent.needs.curiosity = max(0.0, agent.needs.curiosity - 15.0)
        world.log("agent_inspect_cave", f"{agent.name} studies the cave entrance and goes very quiet.", source=agent.id, salience=8, tags=["agent", "cave", "mystery"])
        return
    world.log("agent_inspect_object", f"{agent.name} inspects {obj.name}.", source=agent.id, tags=["agent", "inspect"])
