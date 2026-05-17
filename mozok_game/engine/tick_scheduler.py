from __future__ import annotations

from mozok_game.engine.capabilities import execute_item_action
from mozok_game.engine.commitments import clear_legacy_commitment_cache, sync_legacy_commitment_cache
from mozok_game.engine.director import run_social_director, update_cognitive_trace
from mozok_game.engine.interactions import talk_to_agent
from mozok_game.engine.inventory import has_item, item_name, transfer_item
from mozok_game.engine.needs import apply_environment_needs, update_emotion
from mozok_game.engine.object_effects import choose_default_interaction, execute_inventory_interaction, execute_object_interaction
from mozok_game.engine.pathfinding import next_step_towards
from mozok_game.engine.scene_validation import validate_agent_dialogue
from mozok_game.engine.storylets import run_storylet_director
from mozok_game.engine.world_state import WorldState
from mozok_game.mozok_client.client import BrainClient


def run_agent_ticks(world: WorldState, brain: BrainClient) -> None:
    _run_world_pressure_events(world)
    recent = world.event_log[-10:]
    safety_objects = [obj for obj in world.objects.values() if {"fire", "safety", "shelter"} & set(obj.tags)]
    danger_objects = [obj for obj in world.objects.values() if {"danger", "mystery"} & set(obj.tags)]
    for agent in world.agents.values():
        if not agent.alive:
            continue
        near_safety = any(agent.position.manhattan(obj.position) <= 2 for obj in safety_objects)
        near_danger = any(agent.position.manhattan(obj.position) <= 2 for obj in danger_objects)
        apply_environment_needs(agent, near_safety=near_safety, near_danger=near_danger)
        if _apply_player_commitment(world, agent.id):
            update_emotion(agent)
            update_cognitive_trace(world, agent, agent.last_action, agent.last_rationale)
            _maybe_start_player_conversation(world, agent.id)
            continue
        intent = brain.decide(world, agent, recent)
        apply_agent_intent(world, agent.id, intent.tool_name, intent.parameters, dialogue=intent.dialogue, rationale=intent.rationale)
        update_emotion(agent)
        if not intent.rationale.startswith("MOZOK API:"):
            update_cognitive_trace(world, agent, intent.tool_name, intent.rationale)
        _maybe_start_player_conversation(world, agent.id)
    run_social_director(world, getattr(brain, "weave_social_scene", None))
    world.turn += 1


def _apply_player_commitment(world: WorldState, agent_id: str) -> bool:
    agent = world.agents[agent_id]
    if agent.active_commitment and agent.active_commitment.status == "active":
        sync_legacy_commitment_cache(agent)
        return _apply_active_commitment(world, agent)
    if agent.active_commitment and agent.active_commitment.status != "active":
        agent.active_commitment = None
        clear_legacy_commitment_cache(agent)

    if agent.following_player:
        interrupt = _commitment_interrupt_reason(world, agent)
        if interrupt:
            _interrupt_commitment(world, agent, interrupt)
            return False
        agent.last_action = "follow_player"
        agent.last_rationale = agent.command_reason or "accepted player request to follow"
        agent.current_plan = "follow_player -> You"
        agent.current_target_object_id = ""
        agent.current_target_agent_id = ""
        if agent.position.manhattan(world.player.position) <= 1:
            return True
        blocked = world.occupied_positions(exclude_agent_id=agent.id)
        blocked.discard((world.player.position.x, world.player.position.y))
        step = next_step_towards(world.grid, agent.position, world.player.position, blocked=blocked)
        if step and not (step.x == world.player.position.x and step.y == world.player.position.y):
            agent.position = step
            world.log(
                "agent_follow_player",
                f"{agent.name} follows you. ({agent.last_rationale})",
                source=agent.id,
                salience=5,
                tags=["agent", "movement", "follow"],
                metadata={"agent_id": agent.id},
            )
        else:
            world.log("agent_follow_blocked", f"{agent.name} tries to follow, but cannot find a path.", source=agent.id, tags=["agent", "blocked", "follow"])
        return True

    if agent.command_target_object_id:
        obj = world.objects.get(agent.command_target_object_id)
        if not obj:
            agent.command_target_object_id = ""
            return False
        interrupt = _commitment_interrupt_reason(world, agent, obj)
        if interrupt:
            _interrupt_commitment(world, agent, interrupt)
            return False
        agent.last_action = "obey_player_request"
        agent.last_rationale = agent.command_reason or f"accepted player request to go to {obj.name}"
        agent.current_plan = f"player task -> {obj.name}"
        agent.current_target_object_id = obj.id
        agent.current_target_agent_id = ""
        if agent.position.manhattan(obj.position) <= 1:
            agent.command_target_object_id = ""
            _agent_use_object(world, agent.id, obj.id)
            return True
        blocked = world.occupied_positions(exclude_agent_id=agent.id)
        step = next_step_towards(world.grid, agent.position, obj.position, blocked=blocked)
        if step:
            agent.position = step
            world.log(
                "agent_obey_move",
                f"{agent.name} heads toward {obj.name}. ({agent.last_rationale})",
                source=agent.id,
                salience=5,
                tags=["agent", "movement", "obey"],
                metadata={"agent_id": agent.id, "target": obj.id},
            )
        else:
            world.log("agent_obey_blocked", f"{agent.name} wants to reach {obj.name}, but cannot find a path.", source=agent.id, tags=["agent", "blocked", "obey"])
        return True

    if agent.command_hold_turns > 0:
        agent.command_hold_turns -= 1
        agent.last_action = "wait_after_request"
        agent.last_rationale = agent.command_reason or "waiting after completing the player request"
        agent.current_plan = "wait_after_request"
        agent.current_target_object_id = ""
        agent.current_target_agent_id = ""
        if agent.command_hold_turns in {5, 2}:
            world.log(
                "agent_wait_after_request",
                f"{agent.name} stays nearby after finishing your request.",
                source=agent.id,
                salience=4,
                tags=["agent", "wait", "obey"],
                metadata={"agent_id": agent.id},
            )
        return True

    return False


def _apply_active_commitment(world: WorldState, agent) -> bool:
    commitment = agent.active_commitment
    if not commitment:
        return False
    target_obj = world.objects.get(commitment.target_object_id) if commitment.target_object_id else None
    interrupt = _commitment_interrupt_reason(world, agent, target_obj) or _constraint_interrupt_reason(world, agent, commitment, target_obj)
    if interrupt:
        _interrupt_commitment(world, agent, interrupt)
        return False
    if commitment.expiry_turns and world.turn - commitment.started_turn > commitment.expiry_turns:
        _finish_commitment(world, agent, "expired", f"commitment expired after {commitment.expiry_turns} turns")
        return False

    if commitment.type == "follow":
        agent.last_action = "follow_player"
        agent.last_rationale = commitment.accepted_because or commitment.goal
        agent.current_plan = f"commitment: follow -> You"
        agent.current_target_object_id = ""
        agent.current_target_agent_id = ""
        if agent.position.manhattan(world.player.position) <= int(commitment.constraints.get("stay_within_distance", 2)):
            return True
        blocked = world.occupied_positions(exclude_agent_id=agent.id)
        blocked.discard((world.player.position.x, world.player.position.y))
        step = next_step_towards(world.grid, agent.position, world.player.position, blocked=blocked)
        if step and not (step.x == world.player.position.x and step.y == world.player.position.y):
            agent.position = step
            world.log(
                "agent_follow_player",
                f"{agent.name} follows you under commitment {commitment.id}.",
                source=agent.id,
                salience=5,
                tags=["agent", "movement", "follow", "commitment"],
                metadata={"agent_id": agent.id, "commitment_id": commitment.id},
            )
        else:
            world.log("agent_follow_blocked", f"{agent.name} tries to follow, but cannot find a path.", source=agent.id, tags=["agent", "blocked", "follow"])
        return True

    if commitment.type in {"inspect", "fetch", "go_to_object", "guard"}:
        if not target_obj:
            _finish_commitment(world, agent, "failed", "target object disappeared")
            return False
        agent.last_action = f"commitment_{commitment.type}"
        agent.last_rationale = commitment.accepted_because or commitment.goal
        agent.current_plan = f"commitment: {commitment.type} -> {target_obj.name}"
        agent.current_target_object_id = target_obj.id
        agent.current_target_agent_id = ""
        if agent.position.manhattan(target_obj.position) <= 1:
            if "anchor" in target_obj.capability_accepts and "rope" in agent.inventory and not target_obj.state.get("rope_anchored") and agent.needs.stress + agent.social_to_player.fear > 58:
                execute_item_action(world, agent.id, "rope", target_obj.id, "anchor", commitment.goal)
                return True
            _agent_use_object(world, agent.id, target_obj.id)
            _finish_commitment(world, agent, "succeeded", f"reached and handled {target_obj.name}")
            agent.command_hold_turns = max(agent.command_hold_turns, 6)
            return True
        blocked = world.occupied_positions(exclude_agent_id=agent.id)
        step = next_step_towards(world.grid, agent.position, target_obj.position, blocked=blocked)
        if step:
            agent.position = step
            world.log(
                "agent_commitment_move",
                f"{agent.name} heads toward {target_obj.name} for commitment {commitment.id}.",
                source=agent.id,
                salience=5,
                tags=["agent", "movement", "commitment"],
                metadata={"agent_id": agent.id, "commitment_id": commitment.id, "target": target_obj.id},
            )
        else:
            world.log("agent_obey_blocked", f"{agent.name} wants to reach {target_obj.name}, but cannot find a path.", source=agent.id, tags=["agent", "blocked", "obey"])
        return True

    return False


def _constraint_interrupt_reason(world: WorldState, agent, commitment, obj=None) -> str:
    if agent.health < float(commitment.constraints.get("avoid_if_health_below", -1)):
        return f"health {agent.health:.0f} fell below commitment safety constraint"
    stress_limit = float(commitment.constraints.get("avoid_if_stress_above", 999))
    if agent.needs.stress > stress_limit:
        return f"stress {agent.needs.stress:.0f} exceeded commitment safety constraint"
    required = commitment.constraints.get("requires_item_if_stress_above")
    if isinstance(required, dict):
        item_id = str(required.get("item_id") or "")
        threshold = float(required.get("stress", 999))
        if agent.needs.stress + agent.social_to_player.fear > threshold and item_id and not has_item(world, agent.id, item_id):
            name = obj.name if obj else "target"
            return f"{name} now requires {item_name(item_id)} before continuing safely"
    return ""


def _finish_commitment(world: WorldState, agent, status: str, reason: str) -> None:
    commitment = agent.active_commitment
    if not commitment:
        return
    commitment.status = status
    commitment.interrupt_reason = "" if status == "succeeded" else reason
    agent.commitment_history.append(commitment)
    agent.active_commitment = None
    clear_legacy_commitment_cache(agent, keep_hold=True)
    agent.command_interrupt_reason = "" if status == "succeeded" else reason
    world.log(
        "agent_commitment_finished",
        f"{agent.name}'s commitment {commitment.id} {status}: {reason}.",
        source=agent.id,
        salience=6 if status == "succeeded" else 7,
        tags=["agent", "decision", "commitment", status],
        metadata={"agent_id": agent.id, "commitment_id": commitment.id, "status": status, "reason": reason},
    )


def _commitment_interrupt_reason(world: WorldState, agent, obj=None) -> str:
    urgent, value = agent.needs.most_urgent
    if "wounded" in agent.status_flags and agent.health < 45:
        return f"wound risk is too high to continue; health={agent.health:.0f}"
    if value >= 96:
        return f"{urgent} became critical at {value:.0f}"
    if obj and {"danger", "mystery"} & set(obj.tags) and agent.needs.stress + agent.social_to_player.fear > 150 and "rope" not in agent.inventory:
        return f"fear around {obj.name} exceeded the task without a safer plan"
    return ""


def _interrupt_commitment(world: WorldState, agent, reason: str) -> None:
    if agent.active_commitment:
        agent.active_commitment.status = "interrupted"
        agent.active_commitment.interrupt_reason = reason
        agent.commitment_history.append(agent.active_commitment)
        agent.active_commitment = None
    clear_legacy_commitment_cache(agent)
    agent.command_interrupt_reason = reason
    agent.last_action = "interrupt_task"
    agent.last_rationale = reason
    agent.current_plan = "interrupted player task"
    agent.current_target_object_id = ""
    agent.current_target_agent_id = ""
    world.log(
        "agent_task_interrupted",
        f"{agent.name} stops following the plan: {reason}.",
        source=agent.id,
        salience=8,
        tags=["agent", "task", "interrupt", "decision"],
        metadata={"agent_id": agent.id, "reason": reason},
    )
    world.flash(agent.id, "Task interrupted", reason, kind="decision", intensity=0.8)


def _run_world_pressure_events(world: WorldState) -> None:
    run_storylet_director(world)


def _maybe_start_player_conversation(world: WorldState, agent_id: str) -> None:
    agent = world.agents[agent_id]
    if agent.position.manhattan(world.player.position) > 1:
        return
    if world.turn - agent.last_player_contact_turn < 4:
        return
    recent_tags = {tag for event in world.event_log[-8:] for tag in event.tags}
    has_reason = bool(
        agent.following_player
        or agent.active_commitment
        or agent.command_hold_turns > 0
        or agent.needs.social > 62
        or (_tags_mean_mystery(recent_tags) or {"danger", "conflict", "decision", "social_risk"} & recent_tags)
        or any(claim.listener_id == agent.id for claim in world.claim_log[-4:])
    )
    if not has_reason:
        return
    line = _initiative_line(world, agent_id, recent_tags)
    if any(prior.speaker_id == agent.id and prior.content == line for prior in world.chat_log[-8:]):
        line = _variant_line(world, agent, ["I need a second with you before we move.", "Stay close enough to answer me, please.", "I am trying to make sense of what just changed."])
    agent.last_player_contact_turn = world.turn
    agent.last_dialogue = f"{agent.name}: {line}"
    agent.needs.social = max(0.0, agent.needs.social - 10.0)
    world.chat(agent.id, agent.name, line, source="agent")
    world.log(
        "agent_initiates_chat",
        f"{agent.name}: {line}",
        source=agent.id,
        salience=7,
        tags=["dialogue", "agent", "initiative"],
        metadata={"agent_id": agent.id},
    )


def _initiative_line(world: WorldState, agent_id: str, recent_tags: set[str]) -> str:
    agent = world.agents[agent_id]
    recent_claims = [claim for claim in world.claim_log[-6:] if claim.listener_id == agent.id]
    if recent_claims:
        claim = recent_claims[-1]
        return _variant_line(
            world,
            agent,
            [
                f"You said this: '{claim.text}' I am treating it as unverified until the world proves it.",
                f"I heard your claim about this: '{claim.text}'. I am not turning it into fact yet.",
                f"I am holding your statement separately from the world evidence: '{claim.text}'.",
            ],
        )
    if agent.active_commitment:
        target = world.objects.get(agent.active_commitment.target_object_id) if agent.active_commitment.target_object_id else None
        if target:
            return _variant_line(world, agent, [f"I am still working on this: {agent.active_commitment.goal}. Target: {target.name}.", f"I have not dropped the plan. I am still oriented toward {target.name}."])
        return _variant_line(world, agent, [f"I am still keeping my commitment: {agent.active_commitment.goal}.", "I have not forgotten what I agreed to do."])
    if agent.following_player:
        return _variant_line(world, agent, ["I am still with you. Tell me if this stops being a good idea.", "I am matching your pace. Do not make me guess the next risk."])
    if agent.command_hold_turns > 0:
        return _variant_line(world, agent, ["I did what you asked. I am staying here for a moment in case you need to talk.", "I paused here because you asked. Use the moment if you need it."])
    if _tags_mean_mystery(recent_tags) and agent.traits.get("curiosity", 0.0) > 0.65:
        return _variant_line(world, agent, ["Before we move again: this pattern is becoming more than scenery.", "I keep turning the evidence over in my head. It does not feel random."])
    if "conflict" in recent_tags or "social_risk" in recent_tags:
        return _variant_line(world, agent, ["We need rules before hunger starts making decisions for us.", "If we do not name the rule now, fear will write it for us."])
    if agent.needs.social > 62:
        return _variant_line(world, agent, ["Can we talk for a second? Silence is starting to feel like another problem.", "I need to hear a human answer before this place becomes the only voice."])
    return _variant_line(world, agent, ["I need your attention for a moment.", "Hold on. I need to say something before we keep moving."])


def _variant_line(world: WorldState, agent, options: list[str]) -> str:
    if not options:
        return ""
    seed = sum(ord(char) for char in agent.id) + world.turn
    return options[seed % len(options)]


def _tags_mean_mystery(tags: set[str]) -> bool:
    return bool(tags & {"mystery", "unknown", "evidence", "signal", "sound", "anomaly"})


def apply_agent_intent(world: WorldState, agent_id: str, tool_name: str, parameters: dict, dialogue: str = "", rationale: str = "") -> None:
    agent = world.agents[agent_id]
    agent.last_action = tool_name
    agent.last_rationale = rationale
    agent.current_target_object_id = str(parameters.get("object_id") or "")
    agent.current_target_agent_id = str(parameters.get("target_agent_id") or "")
    agent.current_plan = tool_name
    if tool_name == "talk_to_player":
        agent.current_plan = "talk_to_player -> You"
        agent.current_target_object_id = ""
        agent.current_target_agent_id = ""
        if dialogue:
            validation = validate_agent_dialogue(world, agent, dialogue)
            if validation.changed:
                agent.brain_risk = "Grounded dialogue rewrite: " + "; ".join(validation.rejected_physical_claims[:2])
            dialogue = validation.text
            agent.last_dialogue = dialogue
            world.log("agent_dialogue", dialogue, source=agent.id, salience=6, tags=["dialogue", "agent"], metadata={"agent_id": agent.id, "rationale": rationale})
        else:
            talk_to_agent(world, agent)
        agent.needs.social = max(0.0, agent.needs.social - 12.0)
        return
    if tool_name == "talk_to_agent":
        target_id = str(parameters.get("target_agent_id") or "")
        target = world.agents.get(target_id)
        if not target or not target.alive:
            world.log("agent_wait", f"{agent.name} wanted to speak, but the target was not available.", source=agent.id, tags=["agent", "wait", "dialogue"])
            return
        agent.current_plan = f"talk_to_agent -> {target.name}"
        agent.current_target_object_id = ""
        agent.current_target_agent_id = target.id
        if agent.position.manhattan(target.position) > 1:
            blocked = world.occupied_positions(exclude_agent_id=agent.id)
            blocked.discard((target.position.x, target.position.y))
            step = next_step_towards(world.grid, agent.position, target.position, blocked=blocked)
            if step and not (step.x == target.position.x and step.y == target.position.y):
                agent.position = step
                world.log(
                    "agent_move_to_talk",
                    f"{agent.name} moves toward {target.name} to talk. ({rationale})",
                    source=agent.id,
                    salience=5,
                    tags=["agent", "movement", "dialogue"],
                    metadata={"agent_id": agent.id, "target_agent_id": target.id},
                )
            else:
                world.log("agent_blocked", f"{agent.name} wants to reach {target.name}, but cannot find a path.", source=agent.id, tags=["agent", "blocked", "dialogue"])
            return

        clean = _clean_agent_dialogue(agent.name, target.name, dialogue) or f"{target.name}, we need to compare what we think is happening."
        validation = validate_agent_dialogue(world, agent, clean)
        if validation.changed:
            agent.brain_risk = "Grounded dialogue rewrite: " + "; ".join(validation.rejected_physical_claims[:2])
        clean = validation.text
        agent.last_dialogue = f"{agent.name}: {clean}"
        agent.needs.social = max(0.0, agent.needs.social - 14.0)
        world.last_agent_conversation_turn = world.turn
        world.chat(agent.id, agent.name, clean, source="agent")
        world.log(
            "agent_agent_dialogue",
            f"{agent.name} to {target.name}: {clean}",
            source=agent.id,
            salience=7,
            tags=["dialogue", "agent", "social"],
            metadata={"speaker_id": agent.id, "listener_id": target.id, "rationale": rationale},
        )
        world.flash(target.id, "Social attention", f"{agent.name} deliberately sought {target.name}'s attention.", kind="social", intensity=0.64)
        return
    if tool_name == "give_item":
        target_id = str(parameters.get("target_agent_id") or "")
        item_id = str(parameters.get("item_id") or "")
        target = world.agents.get(target_id)
        if not target or not item_id:
            world.log("agent_wait", f"{agent.name} wants to share something, but the target or item is unclear.", source=agent.id, tags=["agent", "wait", "item"])
            return
        agent.current_plan = f"give_item -> {target.name}"
        agent.current_target_agent_id = target.id
        if agent.position.manhattan(target.position) > 1:
            blocked = world.occupied_positions(exclude_agent_id=agent.id)
            blocked.discard((target.position.x, target.position.y))
            step = next_step_towards(world.grid, agent.position, target.position, blocked=blocked)
            if step and not (step.x == target.position.x and step.y == target.position.y):
                agent.position = step
                world.log("agent_move_to_share", f"{agent.name} moves toward {target.name} to share {item_name(item_id)}.", source=agent.id, salience=5, tags=["agent", "movement", "item"])
            return
        if transfer_item(world, agent.id, target.id, item_id, rationale):
            if dialogue:
                clean = _clean_agent_dialogue(agent.name, target.name, dialogue)
                validation = validate_agent_dialogue(world, agent, clean)
                if validation.changed:
                    agent.brain_risk = "Grounded dialogue rewrite: " + "; ".join(validation.rejected_physical_claims[:2])
                clean = validation.text
                agent.last_dialogue = f"{agent.name}: {clean}"
                world.chat(agent.id, agent.name, clean, source="agent", audience_ids=[target.id])
            if item_id == "medkit" and "wounded" in target.status_flags:
                _use_agent_inventory_item(world, target.id, "medkit")
        else:
            world.log("agent_share_failed", f"{agent.name} wanted to give {item_name(item_id)}, but no longer has it.", source=agent.id, tags=["agent", "item"])
        return
    if tool_name == "use_inventory_item":
        item_id = str(parameters.get("item_id") or "")
        if item_id:
            _use_agent_inventory_item(world, agent_id, item_id)
        else:
            world.log("agent_wait", f"{agent.name} reaches for their pack, then stops.", source=agent.id, tags=["agent", "item"])
        return
    if tool_name == "use_item_on_target":
        item_id = str(parameters.get("item_id") or "")
        target_id = str(parameters.get("target_id") or parameters.get("object_id") or "")
        primitive = str(parameters.get("primitive") or parameters.get("capability") or "inspect")
        agent.current_plan = f"use_item_on_target -> {item_id or 'item'} / {target_id or 'target'}"
        agent.current_target_object_id = target_id
        result = execute_item_action(world, agent_id, item_id, target_id, primitive, rationale)
        if result.ok:
            agent.last_rationale = f"{rationale} Result: {result.message}"
        return
    if tool_name == "move_to_object":
        object_id = parameters.get("object_id")
        obj = world.objects.get(object_id) if object_id else None
        if not obj:
            world.log("agent_wait", f"{agent.name} hesitates. They do not know where to go.", source=agent.id, tags=["agent", "wait"])
            return
        agent.current_plan = f"move_to_object -> {obj.name}"
        agent.current_target_object_id = obj.id
        agent.current_target_agent_id = ""
        if agent.position.manhattan(obj.position) <= 1:
            _agent_use_object(world, agent_id, obj.id, str(parameters.get("interaction_id") or ""))
            return
        blocked = world.occupied_positions(exclude_agent_id=agent.id)
        step = next_step_towards(world.grid, agent.position, obj.position, blocked=blocked)
        if step:
            agent.position = step
            world.log("agent_move", f"{agent.name} moves towards {obj.name}. ({rationale})", source=agent.id, salience=4, tags=["agent", "movement"], metadata={"agent_id": agent.id, "target": obj.id})
        else:
            world.log("agent_blocked", f"{agent.name} wants to reach {obj.name}, but cannot find a path.", source=agent.id, tags=["agent", "blocked"])
        return
    agent.current_plan = "wait"
    agent.current_target_object_id = ""
    agent.current_target_agent_id = ""
    world.log("agent_wait", f"{agent.name} waits, watching the camp. ({rationale})", source=agent.id, salience=3, tags=["agent", "wait"])


def _clean_agent_dialogue(speaker_name: str, target_name: str, dialogue: str) -> str:
    clean = dialogue.strip()
    if not clean:
        return ""
    lowered = clean.lower()
    for prefix in (f"{speaker_name.lower()} to {target_name.lower()}:", f"{speaker_name.lower()}:"):
        if lowered.startswith(prefix):
            return clean.split(":", 1)[1].strip()
    return clean


def _agent_use_object(world: WorldState, agent_id: str, object_id: str, interaction_id: str = "") -> None:
    agent = world.agents[agent_id]
    obj = world.objects[object_id]
    agent.current_plan = f"use_object -> {obj.name}"
    agent.current_target_object_id = obj.id
    agent.current_target_agent_id = ""
    interaction = interaction_id or choose_default_interaction(world, agent.id, obj)
    before_inventory = list(agent.inventory)
    result = execute_object_interaction(world, agent.id, obj, interaction, reason="agent reached object")
    if result.ok and "medkit" in agent.inventory and "medkit" not in before_inventory and "wounded" in agent.status_flags:
        _use_agent_inventory_item(world, agent.id, "medkit")


def _use_agent_inventory_item(world: WorldState, agent_id: str, item_id: str) -> None:
    agent = world.agents[agent_id]
    if item_id not in agent.inventory:
        world.log("agent_item_missing", f"{agent.name} reaches for {item_name(item_id)}, but does not have it.", source=agent.id, tags=["agent", "item"])
        return
    result = execute_inventory_interaction(world, agent.id, item_id, "use", reason="agent inventory use")
    if result.ok and item_id == "medkit":
        world.flash(agent.id, "Wound treated", "Medical supplies changed the body's priorities.", kind="body", intensity=0.8)
