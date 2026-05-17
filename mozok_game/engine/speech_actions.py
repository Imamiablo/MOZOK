from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mozok_game.engine.commitments import clear_legacy_commitment_cache, sync_legacy_commitment_cache
from mozok_game.engine.models import Agent, Commitment, WorldObject
from mozok_game.engine.world_state import WorldState


@dataclass(slots=True)
class SpeechAct:
    kind: str
    action: str = ""
    target: str = "listener"
    object_kind: str = ""
    target_object_id: str = ""
    severity: float = 0.0
    confidence: float = 0.0
    force: str = "request"
    rationale: str = ""


@dataclass(slots=True)
class SpeechClaim:
    text: str
    subject: str = ""
    predicate: str = ""
    object: str = ""
    target_object_id: str = ""
    claim_type: str = "world_fact"
    confidence: float = 0.0


@dataclass(slots=True)
class ParsedSpeech:
    raw_text: str
    acts: list[SpeechAct] = field(default_factory=list)
    claims: list[SpeechClaim] = field(default_factory=list)
    tone: str = "neutral"
    summary: str = ""
    confidence: float = 0.0


@dataclass(slots=True)
class AgentDecision:
    handled: bool
    accepted: bool
    action: str
    reply: str
    reason: str
    target_object_id: str = ""


ACTION_ALIASES = {
    "follow": "follow_player",
    "follow_me": "follow_player",
    "stay_close": "follow_player",
    "come_with_player": "follow_player",
    "stop_follow": "stop_following",
    "stop_following_player": "stop_following",
    "wait_here": "stop_following",
    "go": "go_to_object",
    "go_to_location": "go_to_object",
    "inspect_object": "go_to_object",
    "attack": "hostile",
    "attack_actor": "hostile",
    "threaten": "hostile",
    "threaten_actor": "hostile",
    "intimidate": "hostile",
    "follow_listener": "player_follow_agent",
    "follow_agent": "player_follow_agent",
    "go_with_listener": "player_follow_agent",
    "player_following": "player_follow_agent",
    "player_follow_agent": "player_follow_agent",
}


OBJECT_ALIASES: dict[str, str] = {}


def parsed_speech_from_dict(raw_text: str, data: dict[str, Any]) -> ParsedSpeech:
    acts: list[SpeechAct] = []
    for item in _as_list(data.get("speech_acts") or data.get("acts")):
        if not isinstance(item, dict):
            continue
        kind = _clean_label(item.get("type") or item.get("kind") or "conversation")
        action = _normalise_action(item.get("action") or item.get("requested_action") or item.get("intent") or "")
        object_kind = _normalise_object_kind(item.get("object_kind") or item.get("target_object") or item.get("location") or "")
        target_object_id = str(item.get("target_object_id") or item.get("object_id") or "").strip()
        if kind in {"threat", "hostile", "intimidation"} and not action:
            action = "hostile"
        acts.append(
            SpeechAct(
                kind=kind,
                action=action,
                target=str(item.get("target") or "listener"),
                object_kind=object_kind,
                target_object_id=target_object_id,
                severity=_float(item.get("severity"), 0.0),
                confidence=_float(item.get("confidence"), 0.0),
                force=_clean_label(item.get("force") or ("order" if kind == "order" else "request")),
                rationale=str(item.get("rationale") or ""),
            )
        )

    claims: list[SpeechClaim] = []
    for item in _as_list(data.get("claims")):
        if isinstance(item, str):
            claims.append(SpeechClaim(text=item, confidence=0.65))
        elif isinstance(item, dict):
            text = str(item.get("text") or item.get("claim") or "").strip()
            if text:
                claims.append(
                    SpeechClaim(
                        text=text,
                        subject=str(item.get("subject") or ""),
                        predicate=str(item.get("predicate") or ""),
                        object=str(item.get("object_kind") or item.get("target_object") or item.get("object") or ""),
                        target_object_id=str(item.get("target_object_id") or item.get("object_id") or ""),
                        claim_type=_clean_label(item.get("claim_type") or item.get("type") or "world_fact"),
                        confidence=_float(item.get("confidence"), 0.65),
                    )
                )

    if not acts:
        acts.append(SpeechAct(kind="conversation", confidence=0.35))
    return ParsedSpeech(
        raw_text=raw_text,
        acts=acts,
        claims=claims,
        tone=_clean_label(data.get("emotional_tone") or data.get("tone") or "neutral"),
        summary=str(data.get("summary") or ""),
        confidence=_float(data.get("confidence"), max((act.confidence for act in acts), default=0.0)),
    )


def fallback_interpret_player_speech(text: str, world: WorldState | None = None) -> ParsedSpeech:
    """Tiny offline fallback for when no semantic LLM parser is available.

    The real path is `BrainClient.interpret_speech` in API mode. This fallback
    intentionally handles only obvious demo commands so the prototype remains
    usable offline without pretending to understand open language.
    """

    lower = text.lower()
    acts: list[SpeechAct] = []
    claims: list[SpeechClaim] = []
    if any(mark in lower for mark in ("i will follow you", "i am following you", "i'm following you", "going after you", "go after you", "stay behind you")):
        acts.append(SpeechAct(kind="promise", action="player_follow_agent", confidence=0.7))
    if any(mark in lower for mark in (" i heard ", " я чув", "я чула", "мені здалося", "i think", "я думаю")):
        claims.append(SpeechClaim(text=text, confidence=0.45))
    if "follow" in lower or "stay close" in lower or "за мною" in lower or "поруч" in lower:
        acts.append(SpeechAct(kind="request", action="follow_player", confidence=0.62))
    elif "wait here" in lower or "stay here" in lower or "чекай тут" in lower or "залишайся тут" in lower:
        acts.append(SpeechAct(kind="request", action="stop_following", confidence=0.62))
    elif any(word in lower for word in ("hurt", "kill", "fight", "attack")):
        acts.append(SpeechAct(kind="threat", action="hostile", severity=0.72, confidence=0.58))
    else:
        for alias, kind in _object_alias_index(world).items():
            if alias in lower and any(verb in lower for verb in ("go", "check", "inspect", "йди", "іди", "піди", "перевір")):
                acts.append(SpeechAct(kind="request", action="go_to_object", object_kind=kind, confidence=0.58))
                break
    return ParsedSpeech(raw_text=text, acts=acts or [SpeechAct(kind="conversation", confidence=0.3)], claims=claims, confidence=0.4)


def record_player_claims(world: WorldState, agent: Agent, parsed: ParsedSpeech) -> None:
    for claim in parsed.claims:
        if not _should_record_claim(claim):
            continue
        target = world.objects.get(claim.target_object_id) if claim.target_object_id else _object_for_kind(world, claim.object)
        world.claim(
            speaker_id="player",
            listener_id=agent.id,
            text=claim.text,
            truth_status="unverified",
            confidence=claim.confidence,
            subject=claim.subject,
            predicate=claim.predicate,
            object=claim.object,
            claim_type=claim.claim_type,
            target_object_id=target.id if target else "",
        )


def decide_agent_response(world: WorldState, agent: Agent, parsed: ParsedSpeech) -> AgentDecision:
    act = _primary_action(parsed)
    if not act:
        return AgentDecision(False, False, "none", "", "ordinary conversation")
    action = _normalise_action(act.action)
    if action == "player_follow_agent" or act.kind == "promise":
        return _player_follow_ack(world, agent)
    if action == "stop_following":
        return _stop_following(world, agent)
    if action == "hostile" or act.kind in {"threat", "hostile", "intimidation"}:
        return _hostile_response(world, agent, act)
    if action == "follow_player":
        return _follow_response(world, agent, act, parsed)
    if action == "go_to_object":
        obj = _object_for_act(world, act)
        if not obj:
            return AgentDecision(True, False, "refuse", "I do not know where that is.", "unknown target")
        return _go_to_response(world, agent, obj, act)
    return AgentDecision(False, False, "none", "", "unhandled semantic act")


def apply_agent_decision(world: WorldState, agent: Agent, parsed: ParsedSpeech, decision: AgentDecision) -> None:
    if not decision.handled:
        return
    if decision.action == "follow_player" and decision.accepted:
        _start_commitment(
            world,
            agent,
            commitment_type="follow",
            priority=72.0,
            goal="follow the player while conditions remain acceptable",
            constraints={"stay_within_distance": 2, "avoid_if_health_below": 35, "avoid_if_stress_above": 96},
            accepted_because=decision.reason,
        )
        agent.current_plan = "follow player"
        agent.current_target_object_id = ""
        agent.current_target_agent_id = ""
    elif decision.action == "stop_following":
        agent.command_interrupt_reason = ""
        if agent.active_commitment:
            agent.active_commitment.status = "interrupted"
            agent.active_commitment.interrupt_reason = "player ended commitment"
            agent.commitment_history.append(agent.active_commitment)
            agent.active_commitment = None
        clear_legacy_commitment_cache(agent)
        agent.current_plan = "keep distance"
        agent.current_target_object_id = ""
        agent.current_target_agent_id = ""
    elif decision.action == "go_to_object" and decision.accepted:
        target = world.objects.get(decision.target_object_id)
        constraints = {"return_after": False, "avoid_if_health_below": 35, "avoid_if_stress_above": 92}
        if target and {"danger", "mystery"} & set(target.tags) and "anchor" in target.capability_accepts:
            constraints["requires_item_if_stress_above"] = {"item_id": "rope", "stress": 76}
        _start_commitment(
            world,
            agent,
            commitment_type="inspect",
            target_object_id=decision.target_object_id,
            priority=76.0,
            goal=f"inspect {target.name if target else decision.target_object_id}",
            constraints=constraints,
            expiry_turns=14,
            accepted_because=decision.reason,
        )
        agent.current_plan = f"player task -> {target.name if target else decision.target_object_id}"
        agent.current_target_object_id = decision.target_object_id
        agent.current_target_agent_id = ""
    elif decision.action == "hostile_alarm":
        if agent.active_commitment:
            agent.active_commitment.status = "interrupted"
            agent.active_commitment.interrupt_reason = "hostile social alarm"
            agent.commitment_history.append(agent.active_commitment)
            agent.active_commitment = None
        clear_legacy_commitment_cache(agent)
        agent.current_plan = "hostile social alarm"
        agent.current_target_object_id = ""
        agent.current_target_agent_id = ""
        agent.social_to_player.trust -= 8.0
        agent.social_to_player.fear += 12.0
        agent.social_to_player.resentment += 8.0
        agent.social_to_player.clamp()
    elif decision.action == "acknowledge_player_commitment":
        agent.social_to_player.trust += 1.0
        agent.social_to_player.affinity += 1.0
        agent.social_to_player.clamp()
    elif not decision.accepted:
        force = _primary_action(parsed).force if _primary_action(parsed) else "request"
        agent.social_to_player.trust -= 1.0 if force == "order" else 0.0
        agent.social_to_player.clamp()

    agent.last_dialogue = f"{agent.name}: {decision.reply}"
    agent.brain_focus = _focus_for_decision(decision)
    agent.brain_broadcast = f"Player speech parsed as {_semantic_summary(parsed)}. Decision: {decision.action}. Reason: {decision.reason}"
    world.flash(agent.id, "Decision", decision.reason, kind="decision", intensity=0.72 if decision.accepted else 0.58)
    world.log(
        "agent_speech_decision",
        f"{agent.name}: {decision.reply}",
        source=agent.id,
        salience=8,
        tags=["dialogue", "agent", "decision", decision.action],
        metadata={"agent_id": agent.id, "semantic_summary": _semantic_summary(parsed), "decision": decision.action, "accepted": decision.accepted},
    )


def _start_commitment(
    world: WorldState,
    agent: Agent,
    commitment_type: str,
    priority: float,
    goal: str,
    constraints: dict[str, Any],
    accepted_because: str,
    target_object_id: str = "",
    target_agent_id: str = "",
    expiry_turns: int = 0,
) -> Commitment:
    if agent.active_commitment and agent.active_commitment.status == "active":
        agent.active_commitment.status = "interrupted"
        agent.active_commitment.interrupt_reason = "replaced by newer accepted commitment"
        agent.commitment_history.append(agent.active_commitment)
    commitment = Commitment(
        id=f"commit_{agent.id}_{world.turn}_{len(agent.commitment_history) + 1}",
        agent_id=agent.id,
        issuer_id="player",
        type=commitment_type,
        status="active",
        priority=priority,
        target_object_id=target_object_id,
        target_agent_id=target_agent_id,
        goal=goal,
        constraints=dict(constraints),
        expiry_turns=expiry_turns,
        started_turn=world.turn,
        accepted_because=accepted_because,
        betrayal_if_broken=True,
    )
    agent.active_commitment = commitment
    sync_legacy_commitment_cache(agent)
    agent.command_hold_turns = 0
    world.log(
        "agent_commitment_started",
        f"{agent.name} accepts a {commitment_type} commitment: {goal}.",
        source=agent.id,
        salience=7,
        tags=["agent", "decision", "commitment", "promise"],
        metadata={"agent_id": agent.id, "commitment_id": commitment.id, "type": commitment_type, "target_object_id": target_object_id, "constraints": constraints},
    )
    return commitment


def _primary_action(parsed: ParsedSpeech) -> SpeechAct | None:
    actionable: list[SpeechAct] = []
    for act in parsed.acts:
        action = _normalise_action(act.action)
        if action or act.kind in {"threat", "hostile", "intimidation", "promise"}:
            actionable.append(act)
    if not actionable:
        return None
    return max(actionable, key=lambda act: (act.severity, act.confidence))


def _follow_response(world: WorldState, agent: Agent, act: SpeechAct, parsed: ParsedSpeech) -> AgentDecision:
    score = _obedience_score(agent, act)
    near_danger = any({"danger", "mystery"} & set(obj.tags) and world.player.position.manhattan(obj.position) <= 3 for obj in world.objects.values())
    claim_hint = _unverified_claim_hint(parsed)
    if agent.traits.get("anxiety", 0.0) > 0.65 and near_danger and agent.needs.stress > 55 and score < 72:
        reply = _speech_line(world, "follow_danger_refuse", agent, claim_hint=claim_hint or "I need someone else to know where we went.")
        return AgentDecision(True, False, "refuse", reply, "fear of nearby danger outweighed trust")
    if score >= 48:
        reply = _accept_follow_line(world, agent, act.force, claim_hint)
        return AgentDecision(True, True, "follow_player", reply, f"trust/authority score {score:.0f} was enough to follow")
    reply = _refuse_follow_line(world, agent, claim_hint)
    return AgentDecision(True, False, "refuse", reply, f"trust/authority score {score:.0f} was too low")


def _go_to_response(world: WorldState, agent: Agent, obj: WorldObject, act: SpeechAct) -> AgentDecision:
    tags = set(obj.tags)
    danger = bool({"danger", "mystery"} & tags)
    score = _obedience_score(agent, act)
    if danger and agent.needs.stress + agent.social_to_player.fear > 92 and score < 76:
        return AgentDecision(True, False, "refuse", _speech_line(world, "go_danger_refuse", agent, object_name=obj.name), "danger and fear outweighed the request", obj.id)
    if score >= 42 or {"water", "safety", "shelter", "rest"} & tags:
        return AgentDecision(True, True, "go_to_object", _speech_line(world, "go_accept", agent, object_name=obj.name), f"accepted destination request for {obj.name}", obj.id)
    return AgentDecision(True, False, "refuse", _speech_line(world, "go_low_trust_refuse", agent, object_name=obj.name), "low trust made the destination request fail", obj.id)


def _player_follow_ack(world: WorldState, agent: Agent) -> AgentDecision:
    active_target_id = agent.active_commitment.target_object_id if agent.active_commitment else agent.command_target_object_id
    if active_target_id:
        target = world.objects.get(active_target_id)
        name = target.name if target else "the place I agreed to check"
        return AgentDecision(True, True, "acknowledge_player_commitment", _speech_line(world, "player_follow_ack_target", agent, object_name=name), f"player committed to follow while agent keeps task {name}")
    if agent.following_player or (agent.active_commitment and agent.active_commitment.type == "follow"):
        return AgentDecision(True, True, "acknowledge_player_commitment", _speech_line(world, "player_follow_ack_together", agent), "player affirmed a shared movement plan")
    return AgentDecision(True, True, "acknowledge_player_commitment", _speech_line(world, "player_intention_ack", agent), "player stated an intention rather than an external fact")


def _stop_following(world: WorldState, agent: Agent) -> AgentDecision:
    if agent.following_player:
        return AgentDecision(True, True, "stop_following", _speech_line(world, "stop_following", agent), "player ended follow commitment")
    return AgentDecision(True, True, "stop_following", _speech_line(world, "keep_distance", agent), "player requested distance")


def _hostile_response(world: WorldState, agent: Agent, act: SpeechAct) -> AgentDecision:
    dominance = agent.traits.get("dominance", 0.4)
    empathy = agent.traits.get("empathy", 0.45)
    anxiety = agent.traits.get("anxiety", 0.45)
    if dominance > 0.65:
        reply = _speech_line(world, "hostile_dominant", agent)
    elif empathy > 0.65:
        reply = _speech_line(world, "hostile_empathy", agent)
    elif anxiety > 0.65:
        reply = _speech_line(world, "hostile_anxious", agent)
    else:
        reply = _speech_line(world, "hostile_default", agent)
    severity = max(0.35, act.severity)
    return AgentDecision(True, False, "hostile_alarm", reply, f"semantic parser read a threat/intimidation with severity {severity:.2f}")


def _obedience_score(agent: Agent, act: SpeechAct) -> float:
    social = agent.social_to_player
    score = social.trust + social.affinity * 0.35 - social.fear * 0.45 - social.resentment * 0.35
    score -= agent.needs.stress * 0.18
    score += agent.traits.get("loyalty", 0.5) * 8.0
    score += agent.traits.get("agreeableness", 0.5) * 5.0
    score -= agent.traits.get("dominance", 0.5) * 4.0
    score -= agent.traits.get("caution", 0.5) * max(0.0, agent.needs.stress - 45.0) * 0.08
    if act.force == "order" or act.kind == "order":
        score += 9.0
        if agent.traits.get("dominance", 0.0) > 0.65:
            score -= 7.0
    if agent.traits.get("empathy", 0.0) > 0.65:
        score += 8.0
    score += min(10.0, agent.traits.get("curiosity", 0.0) * agent.needs.curiosity * 0.12)
    return score


def _object_for_kind(world: WorldState, kind: str) -> WorldObject | None:
    kind = _normalise_object_kind(kind, world)
    query = kind.replace("_", " ")
    for obj in world.objects.values():
        labels = _object_labels(obj)
        if obj.kind == kind or query in labels:
            return obj
    return None


def _object_for_act(world: WorldState, act: SpeechAct) -> WorldObject | None:
    if act.target_object_id and act.target_object_id in world.objects:
        return world.objects[act.target_object_id]
    return _object_for_kind(world, act.object_kind)


def _should_record_claim(claim: SpeechClaim) -> bool:
    if claim.claim_type in {"player_intention", "player_commitment", "promise", "opinion", "navigation_status", "conversation"}:
        return False
    if claim.subject and _clean_label(claim.subject) in {"player", "you", "self"} and not claim.object:
        return False
    return True


def _normalise_action(value: Any) -> str:
    label = _clean_label(value)
    return ACTION_ALIASES.get(label, label)


def _normalise_object_kind(value: Any, world: WorldState | None = None) -> str:
    label = _clean_label(value)
    return _object_alias_index(world).get(label, label)


def _object_alias_index(world: WorldState | None = None) -> dict[str, str]:
    aliases = dict(OBJECT_ALIASES)
    if not world:
        return aliases
    for obj in world.objects.values():
        for label in _object_labels(obj):
            aliases[label] = obj.kind
            aliases[label.replace(" ", "_")] = obj.kind
    return aliases


def _object_labels(obj: WorldObject) -> set[str]:
    labels = {
        obj.id.lower().replace("_", " "),
        obj.kind.lower().replace("_", " "),
        obj.name.lower(),
        *(tag.lower().replace("_", " ") for tag in obj.tags),
        *(alias.lower().replace("_", " ") for alias in obj.aliases),
    }
    for chunk in (obj.id, obj.kind, obj.name, *obj.aliases):
        labels.update(part for part in str(chunk).lower().replace("_", " ").split() if len(part) > 2)
    return {label for label in labels if label}


def _clean_label(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _unverified_claim_hint(parsed: ParsedSpeech) -> str:
    claims = [claim for claim in parsed.claims if _should_record_claim(claim)]
    if not claims:
        return ""
    claim = claims[0].text
    return f"I only know that you said: {claim}"


def _accept_follow_line(world: WorldState, agent: Agent, force: str, claim_hint: str) -> str:
    caveat = f" {claim_hint}" if claim_hint else ""
    if agent.traits.get("dominance", 0.0) > 0.65:
        return _speech_line(world, "follow_accept_dominant", agent, claim_hint=caveat)
    if agent.traits.get("empathy", 0.0) > 0.65 or agent.traits.get("anxiety", 0.0) > 0.65:
        return _speech_line(world, "follow_accept_careful", agent, claim_hint=caveat)
    if force == "order":
        return _speech_line(world, "follow_accept_order", agent, claim_hint=caveat)
    return _speech_line(world, "follow_accept", agent, claim_hint=caveat)


def _refuse_follow_line(world: WorldState, agent: Agent, claim_hint: str) -> str:
    caveat = f" {claim_hint}" if claim_hint else ""
    if agent.traits.get("dominance", 0.0) > 0.65:
        return _speech_line(world, "follow_refuse_dominant", agent, claim_hint=caveat)
    if agent.traits.get("anxiety", 0.0) > 0.65:
        return _speech_line(world, "follow_refuse_anxious", agent, claim_hint=caveat)
    return _speech_line(world, "follow_refuse", agent, claim_hint=caveat)


def _speech_line(world: WorldState, key: str, agent: Agent, **context: str) -> str:
    templates = world.dialogue_templates.get("speech_decision_lines") if isinstance(world.dialogue_templates.get("speech_decision_lines"), dict) else {}
    raw = templates.get(key) if isinstance(templates, dict) else None
    fallback = _speech_fallbacks().get(key, "{agent}: I hear you.")
    if isinstance(raw, list) and raw:
        template = str(raw[(world.turn + len(agent.id)) % len(raw)])
    else:
        template = str(raw or fallback)
    values = {"agent": agent.name, "claim_hint": "", "object_name": "there", **context}
    for name, value in values.items():
        template = template.replace("{" + name + "}", str(value))
    return template.removeprefix(f"{agent.name}: ").strip()


def _speech_fallbacks() -> dict[str, str]:
    return {
        "follow_danger_refuse": "I will not walk into danger on that alone. {claim_hint}",
        "go_danger_refuse": "No. I am not going to {object_name} alone.",
        "go_accept": "All right. I will go to {object_name}.",
        "go_low_trust_refuse": "I do not trust that enough to go to {object_name}.",
        "player_follow_ack_target": "Good. Stay close; I am still heading to {object_name}.",
        "player_follow_ack_together": "Then we stay together. I am following your lead.",
        "player_intention_ack": "Okay. I understand that as your intention, not as proof about the world.",
        "stop_following": "Okay. I will stay back.",
        "keep_distance": "I was not following you, but I will keep my distance.",
        "hostile_dominant": "Try it and this group becomes a courtroom with fists.",
        "hostile_empathy": "No. Stop. I will not let this become violence.",
        "hostile_anxious": "Back away. I cannot think while you are talking like that.",
        "hostile_default": "If this is a test, it is a cruel one. Back off.",
        "follow_accept_dominant": "Fine. I will follow, but I am watching the shared resources and your decisions.{claim_hint}",
        "follow_accept_careful": "Okay. I will stay close to you. Please do not make me regret it.{claim_hint}",
        "follow_accept_order": "I will follow. But I heard that as an order, not a conversation.{claim_hint}",
        "follow_accept": "All right. Lead the way.{claim_hint}",
        "follow_refuse_dominant": "No. Not on trust alone. Tell me why first.{claim_hint}",
        "follow_refuse_anxious": "I cannot. Not while everyone is scattered and I am this scared.{claim_hint}",
        "follow_refuse": "Not yet. I need a better reason.{claim_hint}",
    }


def _focus_for_decision(decision: AgentDecision) -> str:
    if decision.action == "follow_player" and decision.accepted:
        return "Following the player by choice."
    if decision.action == "go_to_object" and decision.accepted:
        return "Carrying out a player request."
    if decision.action == "hostile_alarm":
        return "Player threat changed the social situation."
    if not decision.accepted:
        return "Refused the player request."
    return "Updated commitment."


def _semantic_summary(parsed: ParsedSpeech) -> str:
    acts = ", ".join(f"{act.kind}:{act.action or 'none'}" for act in parsed.acts)
    claims = f"; claims={len(parsed.claims)}" if parsed.claims else ""
    return f"{acts or 'conversation'}{claims}"


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]
