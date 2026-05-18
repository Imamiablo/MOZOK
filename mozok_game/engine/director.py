from __future__ import annotations

from typing import Any

from mozok_game.engine.models import Agent
from mozok_game.engine.relationships import apply_relationship_delta
from mozok_game.engine.scene_validation import validate_agent_dialogue
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

    if _tags_mean_mystery(tags) and agent.traits.get("curiosity", 0.0) > 0.65:
        focus = "Mystery signal is competing for attention."
        score = 0.91
        risk = "mystery"
    elif _tags_mean_resource_pressure(tags) and (agent.traits.get("dominance", 0.0) > 0.6 or "control" in agent.values):
        focus = "Supply trust is under pressure."
        score = 0.88
        risk = "social"
    elif "danger" in tags and (agent.traits.get("empathy", 0.0) > 0.65 or agent.traits.get("caution", 0.0) > 0.65):
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
    configured = world.dialogue_templates.get("dialogue_options")
    if isinstance(configured, list) and configured:
        return [dict(item) for item in configured if isinstance(item, dict) and item.get("id") and item.get("label")][:5]
    options = [
        {"id": "memory", "label": "Ask what they remember"},
        {"id": "intent", "label": "Ask what they plan"},
    ]
    tags = _recent_tags(world)
    if agent.traits.get("dominance", 0.0) > 0.6 and _tags_mean_resource_pressure(tags):
        options.append({"id": "challenge", "label": "Challenge their concern"})
    elif agent.emotion in {"afraid", "tired"} or agent.needs.stress > 50:
        options.append({"id": "reassure", "label": "Reassure them"})
    else:
        options.append({"id": "probe", "label": "Press for a theory"})
    return options


def apply_dialogue_choice(world: WorldState, agent: Agent, choice_id: str) -> str:
    tags = _recent_tags(world)
    configured = _apply_configured_dialogue_choice(world, agent, choice_id, tags)
    if configured:
        return configured
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
        line = f"{agent.name}: Pressure makes people careless. I want reasons, not just orders."
        world.flash(agent.id, "Belief reinforced", "Trust needs visible rules when pressure rises.", kind="belief", intensity=0.78)
    elif choice_id == "reassure":
        agent.social_to_player.trust += 5.0
        agent.social_to_player.fear = max(0.0, agent.social_to_player.fear - 4.0)
        agent.needs.stress = max(0.0, agent.needs.stress - 8.0)
        agent.social_to_player.clamp()
        line = f"{agent.name}: Good. Say that again if I start spiralling."
        world.flash(agent.id, "State update", "Player reassurance lowered stress and raised trust.", kind="state", intensity=0.65)
    else:
        theory = _theory_for(world, agent)
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


def _apply_configured_dialogue_choice(world: WorldState, agent: Agent, choice_id: str, tags: set[str]) -> str:
    choices = world.dialogue_templates.get("dialogue_choices")
    if not isinstance(choices, dict) or choice_id not in choices:
        return ""
    spec = choices.get(choice_id)
    if not isinstance(spec, dict):
        return ""
    for key, amount in dict(spec.get("social_delta") or {}).items():
        if hasattr(agent.social_to_player, str(key)):
            setattr(agent.social_to_player, str(key), float(getattr(agent.social_to_player, str(key))) + float(amount))
    agent.social_to_player.clamp()
    _apply_need_delta(agent, dict(spec.get("need_delta") or {}))
    context = {
        "agent": agent.name,
        "focus": agent.brain_focus,
        "plan": agent.current_plan or agent.last_action,
        "memory": _pick_memory(agent, tags) or (agent.memory_snippets[0] if agent.memory_snippets else "nothing certain"),
        "theory": _theory_for(world, agent),
        "pressure": ", ".join(sorted(tags)) or "the situation",
    }
    reply = _format_template(str(spec.get("reply_template") or "{agent}: I hear you."), context)
    line = reply if reply.lower().startswith(f"{agent.name.lower()}:") else f"{agent.name}: {reply}"
    flash = spec.get("flash") if isinstance(spec.get("flash"), dict) else {}
    if flash:
        world.flash(
            agent.id,
            str(flash.get("title") or "Dialogue"),
            _format_template(str(flash.get("content") or ""), context),
            kind=str(flash.get("kind") or "focus"),
            intensity=float(flash.get("intensity", 0.65)),
        )
    agent.last_dialogue = line
    world.log(
        "player_dialogue_choice",
        line,
        source=agent.id,
        salience=float(spec.get("salience", 7)),
        tags=list(spec.get("tags") or ["dialogue", "social", "choice"]),
        metadata={"agent_id": agent.id, "choice_id": choice_id, "configured": True},
    )
    return line


def trigger_scripted_moment(world: WorldState, moment_id: str) -> None:
    _trigger_data_moment(world, moment_id)


def _trigger_data_moment(world: WorldState, moment_id: str) -> bool:
    spec = world.scripted_moments.get(moment_id)
    if not isinstance(spec, dict):
        return False
    flag = str(spec.get("flag") or moment_id)
    if spec.get("once") and flag in world.scripted_flags:
        return True
    if spec.get("once"):
        world.scripted_flags.add(flag)
    selected = _select_agent_from_spec(world, dict(spec.get("select_agent") or {}))
    context = {"agent": selected.name if selected else "Someone", "moment_id": moment_id}
    for effect in spec.get("effects") or []:
        if isinstance(effect, dict):
            _apply_moment_effect(world, effect, selected, context)
    return True


def _select_agent_from_spec(world: WorldState, selector: dict[str, Any]) -> Agent | None:
    if not selector:
        return None
    traits = dict(selector.get("prefer_traits") or {})
    needs = dict(selector.get("prefer_needs") or {})
    social = dict(selector.get("prefer_social") or {})

    def score(agent: Agent) -> float:
        value = 0.0
        for key, weight in traits.items():
            value += agent.traits.get(str(key), 0.0) * float(weight)
        for key, weight in needs.items():
            if hasattr(agent.needs, str(key)):
                value += float(getattr(agent.needs, str(key))) * float(weight)
        for key, weight in social.items():
            if hasattr(agent.social_to_player, str(key)):
                value += float(getattr(agent.social_to_player, str(key))) * float(weight)
        return value

    return _best_agent(world, score)


def _apply_moment_effect(world: WorldState, effect: dict[str, Any], selected: Agent | None, context: dict[str, str]) -> None:
    effect_type = str(effect.get("type") or "")
    target = selected if effect.get("target", "selected_agent") == "selected_agent" else None
    if effect_type == "agent_social_delta" and target:
        for key, amount in dict(effect.get("delta") or {}).items():
            if hasattr(target.social_to_player, str(key)):
                setattr(target.social_to_player, str(key), float(getattr(target.social_to_player, str(key))) + float(amount))
        target.social_to_player.clamp()
        return
    if effect_type == "agent_need_delta" and target:
        _apply_need_delta(target, dict(effect.get("delta") or {}))
        return
    if effect_type == "all_agent_need_delta":
        for agent in world.agents.values():
            _apply_need_delta(agent, dict(effect.get("delta") or {}))
        return
    if effect_type == "flash" and target:
        flag = f"{effect.get('title', 'flash')}:{target.id}:{effect.get('content_template', '')}"
        if effect.get("once_per_agent") and flag in world.scripted_flags:
            return
        if effect.get("once_per_agent"):
            world.scripted_flags.add(flag)
        world.flash(
            target.id,
            str(effect.get("title") or "Moment"),
            _format_template(str(effect.get("content_template") or ""), context),
            kind=str(effect.get("kind") or "memory"),
            intensity=float(effect.get("intensity", 0.7)),
        )
        return
    if effect_type == "flash_all_agents":
        for agent in world.agents.values():
            world.flash(
                agent.id,
                str(effect.get("title") or "Moment"),
                _format_template(str(effect.get("content_template") or ""), {"agent": agent.name, **context}),
                kind=str(effect.get("kind") or "memory"),
                intensity=float(effect.get("intensity", 0.7)),
            )
        return
    if effect_type == "flash_best_agent":
        agent = _select_agent_from_spec(world, {"prefer_traits": dict(effect.get("prefer_traits") or {})})
        if agent:
            _apply_need_delta(agent, dict(effect.get("need_delta") or {}))
            world.flash(
                agent.id,
                str(effect.get("title") or "Moment"),
                _format_template(str(effect.get("content_template") or ""), {"agent": agent.name, **context}),
                kind=str(effect.get("kind") or "memory"),
                intensity=float(effect.get("intensity", 0.7)),
            )
        return
    if effect_type == "log":
        source = selected.id if selected else str(effect.get("source") or "director")
        source_tags = set(effect.get("source_tags") or [])
        if source_tags:
            obj = _object_with_any_tag(world, source_tags)
            source = obj.id if obj else source
        flag = f"log:{effect.get('event_type', '')}:{source}:{effect.get('content_template', '')}"
        if effect.get("once_per_agent") and flag in world.scripted_flags:
            return
        if effect.get("once_per_agent"):
            world.scripted_flags.add(flag)
        world.log(
            str(effect.get("event_type") or "scripted_moment"),
            _format_template(str(effect.get("content_template") or ""), context),
            source=source,
            salience=float(effect.get("salience", 7)),
            tags=list(effect.get("tags") or ["moment"]),
            metadata={"agent_id": selected.id if selected else "", "moment_id": context.get("moment_id", "")},
        )


def _apply_need_delta(agent: Agent, delta: dict[str, Any]) -> None:
    for key, amount in delta.items():
        if hasattr(agent.needs, str(key)):
            setattr(agent.needs, str(key), float(getattr(agent.needs, str(key))) + float(amount))
    agent.needs.clamp()


def _format_template(template: str, context: dict[str, str]) -> str:
    result = template
    for key, value in context.items():
        result = result.replace("{" + key + "}", str(value))
    return result


def _best_agent(world: WorldState, scorer) -> Agent | None:
    agents = [agent for agent in world.agents.values() if agent.alive]
    if not agents:
        return None
    return max(agents, key=scorer)


def _object_with_tags(world: WorldState, wanted_tags: set[str]):
    for obj in world.objects.values():
        if wanted_tags <= set(obj.tags):
            return obj
    return None


def _object_with_any_tag(world: WorldState, wanted_tags: set[str]):
    for obj in world.objects.values():
        if wanted_tags & set(obj.tags):
            return obj
    return None


def run_social_director(world: WorldState, scene_weaver=None) -> None:
    if world.turn - world.last_agent_conversation_turn < 2:
        return
    pairs = _nearby_pairs(world)
    if not pairs:
        return

    tags = _recent_tags(world)
    speaker, listener = _choose_pair(pairs, tags)
    if not speaker or not listener:
        return

    motive_key, motive_data = _social_motive(world, speaker, listener, tags)
    line = ""
    if scene_weaver:
        line = str(scene_weaver(world, speaker, listener, motive_data) or "").strip()
    if not line:
        line = _agent_to_agent_line(world, speaker, listener, tags, motive_key=motive_key)
    if line.lower().startswith(f"{speaker.name.lower()}:"):
        line = line.split(":", 1)[1].strip()
    validation = validate_agent_dialogue(world, speaker, line)
    if validation.changed:
        speaker.brain_risk = "Grounded dialogue rewrite: " + "; ".join(validation.rejected_physical_claims[:2])
    line = validation.text
    if any(previous.speaker_id == speaker.id and previous.content == line for previous in world.chat_log[-8:]):
        line = _agent_to_agent_line(world, speaker, listener, tags, motive_key=motive_key, variant_salt=1)
    speaker.last_dialogue = f"{speaker.name}: {line}"
    world.last_agent_conversation_turn = world.turn
    world.chat(speaker.id, speaker.name, line, source="agent", audience_ids=[listener.id])
    apply_relationship_delta(speaker, listener.id, {"trust": 0.2, "affinity": 0.6})
    apply_relationship_delta(listener, speaker.id, {"affinity": 0.4})
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
    for tag in sorted(tags, key=len, reverse=True):
        for memory in agent.memory_snippets:
            if tag and tag.replace("_", " ") in memory.lower():
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
        if _tags_mean_resource_pressure(tags):
            speaker = max((left, right), key=lambda agent: agent.traits.get("dominance", 0.0) + agent.traits.get("caution", 0.0))
            if speaker.traits.get("dominance", 0.0) > 0.5:
                return (speaker, right if speaker is left else left)
        if _tags_mean_mystery(tags):
            speaker = max((left, right), key=lambda agent: agent.traits.get("curiosity", 0.0))
            if speaker.traits.get("curiosity", 0.0) > 0.5:
                return (speaker, right if speaker is left else left)
        if "danger" in tags:
            speaker = max((left, right), key=lambda agent: agent.traits.get("empathy", 0.0) + agent.traits.get("caution", 0.0))
            if speaker.traits.get("empathy", 0.0) > 0.5 or speaker.traits.get("caution", 0.0) > 0.5:
                return (speaker, right if speaker is left else left)
    return pairs[0] if pairs else (None, None)


def _social_motive(world: WorldState, speaker: Agent, listener: Agent, tags: set[str]) -> tuple[str, dict[str, Any]]:
    key = "need_pressure"
    if speaker.traits.get("dominance", 0.0) > 0.6 and _tags_mean_resource_pressure(tags):
        key = "resource_control"
    elif speaker.traits.get("curiosity", 0.0) > 0.65 and _tags_mean_mystery(tags):
        key = "mystery_curiosity"
    elif speaker.traits.get("empathy", 0.0) > 0.65 and ("danger" in tags or "sound" in tags):
        key = "danger_warning"
    urgent, value = speaker.needs.most_urgent
    return (
        key,
        {
            "dialogue_pack_key": key,
            "speaker_id": speaker.id,
            "listener_id": listener.id,
            "recent_tags": sorted(tags),
            "urgent_need": urgent,
            "urgent_value": round(value, 1),
            "pressure": dict(world.pressure),
        },
    )


def _agent_to_agent_line(world: WorldState, speaker: Agent, listener: Agent, tags: set[str], motive_key: str = "", variant_salt: int = 0) -> str:
    social_lines = world.dialogue_templates.get("social_lines") if isinstance(world.dialogue_templates.get("social_lines"), dict) else {}
    urgent, value = speaker.needs.most_urgent
    return _dialogue_template(social_lines, motive_key or "need_pressure", speaker, listener, tags, urgent=urgent, value=f"{value:.0f}", variant_salt=variant_salt)


def _dialogue_template(templates: dict[str, Any], key: str, speaker: Agent, listener: Agent, tags: set[str], variant_salt: int = 0, **extra: str) -> str:
    raw = templates.get(key)
    if isinstance(raw, list) and raw:
        template = str(raw[(len(tags) + len(speaker.id) + len(listener.id) + variant_salt) % len(raw)])
    else:
        template = str(raw or "{speaker}: {listener}, I need to say this plainly: {pressure} matters right now.")
    context = {
        "speaker": speaker.name,
        "listener": listener.name,
        "pressure": ", ".join(sorted(tags)) or "the situation",
        **extra,
    }
    for name, value in context.items():
        template = template.replace("{" + name + "}", value)
    prefix = f"{speaker.name}: "
    return template.removeprefix(prefix)


def _theory_for(world: WorldState, agent: Agent) -> str:
    templates = world.dialogue_templates.get("theories") if isinstance(world.dialogue_templates.get("theories"), dict) else {}
    if agent.traits.get("curiosity", 0.0) > 0.75:
        return str(templates.get("curiosity") or "This place feels designed. Not haunted. Designed.")
    if agent.traits.get("dominance", 0.0) > 0.65:
        return str(templates.get("dominance") or "The first real monster here will be bad accounting.")
    if agent.traits.get("empathy", 0.0) > 0.65:
        return str(templates.get("empathy") or "The pressure is pushing us apart. That is how people get hurt.")
    return str(templates.get("default") or "Something here is arranging pressure on purpose.")


def _tags_mean_resource_pressure(tags: set[str]) -> bool:
    return bool(tags & {"food", "supplies", "scarce", "scarcity", "resource", "resources", "shared_resource"})


def _tags_mean_mystery(tags: set[str]) -> bool:
    return bool(tags & {"mystery", "unknown", "evidence", "signal", "sound", "anomaly"})
