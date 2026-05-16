from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from mozok_game.engine.models import Agent, WorldObject
from mozok_game.engine.world_state import WorldState


@dataclass(slots=True)
class SpeechAct:
    kind: str
    action: str = ""
    target: str = "listener"
    object_kind: str = ""
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


OBJECT_ALIASES = {
    "fire": "campfire",
    "camp": "campfire",
    "camp_fire": "campfire",
    "food": "food_crate",
    "crate": "food_crate",
    "supplies": "food_crate",
    "ration": "food_crate",
    "water": "water_source",
    "spring": "water_source",
    "cave": "cave_entrance",
    "cave entrance": "cave_entrance",
    "radio": "broken_radio",
    "shelter": "shelter",
    "medkit": "medkit",
    "medicine": "medkit",
    "knife": "knife",
    "rope": "rope",
    "berries": "poisonous_berries",
    "berry": "poisonous_berries",
    "journal": "journal_page",
    "page": "journal_page",
    "lockbox": "locked_supply_box",
    "box": "locked_supply_box",
}


def parsed_speech_from_dict(raw_text: str, data: dict[str, Any]) -> ParsedSpeech:
    acts: list[SpeechAct] = []
    for item in _as_list(data.get("speech_acts") or data.get("acts")):
        if not isinstance(item, dict):
            continue
        kind = _clean_label(item.get("type") or item.get("kind") or "conversation")
        action = _normalise_action(item.get("action") or item.get("requested_action") or item.get("intent") or "")
        object_kind = _normalise_object_kind(item.get("object_kind") or item.get("target_object") or item.get("location") or "")
        if kind in {"threat", "hostile", "intimidation"} and not action:
            action = "hostile"
        acts.append(
            SpeechAct(
                kind=kind,
                action=action,
                target=str(item.get("target") or "listener"),
                object_kind=object_kind,
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


def fallback_interpret_player_speech(text: str) -> ParsedSpeech:
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
        for alias, kind in OBJECT_ALIASES.items():
            if alias in lower and any(verb in lower for verb in ("go", "check", "inspect", "йди", "іди", "піди", "перевір")):
                acts.append(SpeechAct(kind="request", action="go_to_object", object_kind=kind, confidence=0.58))
                break
    return ParsedSpeech(raw_text=text, acts=acts or [SpeechAct(kind="conversation", confidence=0.3)], claims=claims, confidence=0.4)


def record_player_claims(world: WorldState, agent: Agent, parsed: ParsedSpeech) -> None:
    for claim in parsed.claims:
        if not _should_record_claim(claim):
            continue
        target = _object_for_kind(world, claim.object)
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
        return _stop_following(agent)
    if action == "hostile" or act.kind in {"threat", "hostile", "intimidation"}:
        return _hostile_response(agent, act)
    if action == "follow_player":
        return _follow_response(world, agent, act, parsed)
    if action == "go_to_object":
        obj = _object_for_kind(world, act.object_kind)
        if not obj:
            return AgentDecision(True, False, "refuse", "I do not know where that is.", "unknown target")
        return _go_to_response(world, agent, obj, act)
    return AgentDecision(False, False, "none", "", "unhandled semantic act")


def apply_agent_decision(world: WorldState, agent: Agent, parsed: ParsedSpeech, decision: AgentDecision) -> None:
    if not decision.handled:
        return
    if decision.action == "follow_player" and decision.accepted:
        agent.following_player = True
        agent.command_target_object_id = ""
        agent.command_reason = decision.reason
        agent.command_source = "player"
        agent.command_priority = 72.0
        agent.command_started_turn = world.turn
        agent.command_interrupt_reason = ""
        agent.command_hold_turns = 0
        agent.current_plan = "follow player"
        agent.current_target_object_id = ""
        agent.current_target_agent_id = ""
    elif decision.action == "stop_following":
        agent.following_player = False
        agent.command_target_object_id = ""
        agent.command_reason = ""
        agent.command_interrupt_reason = ""
        agent.command_hold_turns = 0
        agent.current_plan = "keep distance"
        agent.current_target_object_id = ""
        agent.current_target_agent_id = ""
    elif decision.action == "go_to_object" and decision.accepted:
        agent.following_player = False
        agent.command_target_object_id = decision.target_object_id
        agent.command_reason = decision.reason
        agent.command_source = "player"
        agent.command_priority = 76.0
        agent.command_started_turn = world.turn
        agent.command_interrupt_reason = ""
        agent.command_hold_turns = 6
        target = world.objects.get(decision.target_object_id)
        agent.current_plan = f"player task -> {target.name if target else decision.target_object_id}"
        agent.current_target_object_id = decision.target_object_id
        agent.current_target_agent_id = ""
    elif decision.action == "hostile_alarm":
        agent.following_player = False
        agent.command_target_object_id = ""
        agent.command_hold_turns = 0
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
    near_cave = bool(world.object_by_kind("cave_entrance") and world.player.position.manhattan(world.object_by_kind("cave_entrance").position) <= 3)
    claim_hint = _unverified_claim_hint(parsed)
    if agent.id == "mira" and near_cave and agent.needs.stress > 55 and score < 72:
        reply = f"I will not go into the cave on that alone. {claim_hint or 'I need someone else to know where we went.'}"
        return AgentDecision(True, False, "refuse", reply, "fear of the cave outweighed trust")
    if score >= 48:
        reply = _accept_follow_line(agent, act.force, claim_hint)
        return AgentDecision(True, True, "follow_player", reply, f"trust/authority score {score:.0f} was enough to follow")
    reply = _refuse_follow_line(agent, claim_hint)
    return AgentDecision(True, False, "refuse", reply, f"trust/authority score {score:.0f} was too low")


def _go_to_response(world: WorldState, agent: Agent, obj: WorldObject, act: SpeechAct) -> AgentDecision:
    danger = obj.kind == "cave_entrance"
    score = _obedience_score(agent, act)
    if danger and agent.needs.stress + agent.social_to_player.fear > 92 and score < 76:
        return AgentDecision(True, False, "refuse", f"No. I am not going to {obj.name} alone.", "danger and fear outweighed the request", obj.id)
    if score >= 42 or obj.kind in {"water_source", "campfire", "shelter"}:
        return AgentDecision(True, True, "go_to_object", f"All right. I will go to {obj.name}.", f"accepted destination request for {obj.name}", obj.id)
    return AgentDecision(True, False, "refuse", f"I do not trust that enough to go to {obj.name}.", "low trust made the destination request fail", obj.id)


def _player_follow_ack(world: WorldState, agent: Agent) -> AgentDecision:
    if agent.command_target_object_id:
        target = world.objects.get(agent.command_target_object_id)
        name = target.name if target else "the place I agreed to check"
        return AgentDecision(True, True, "acknowledge_player_commitment", f"Good. Stay close; I am still heading to {name}.", f"player committed to follow while agent keeps task {name}")
    if agent.following_player:
        return AgentDecision(True, True, "acknowledge_player_commitment", "Then we stay together. I am following your lead.", "player affirmed a shared movement plan")
    return AgentDecision(True, True, "acknowledge_player_commitment", "Okay. I understand that as your intention, not as proof about the island.", "player stated an intention rather than an external fact")


def _stop_following(agent: Agent) -> AgentDecision:
    if agent.following_player:
        return AgentDecision(True, True, "stop_following", "Okay. I will stay back.", "player ended follow commitment")
    return AgentDecision(True, True, "stop_following", "I was not following you, but I will keep my distance.", "player requested distance")


def _hostile_response(agent: Agent, act: SpeechAct) -> AgentDecision:
    if agent.id == "boris":
        reply = "Try it and this camp becomes a courtroom with fists."
    elif agent.id == "mira":
        reply = "No. Stop. I will not let this become violence."
    else:
        reply = "If this is a test, it is a cruel one. Back off."
    severity = max(0.35, act.severity)
    return AgentDecision(True, False, "hostile_alarm", reply, f"semantic parser read a threat/intimidation with severity {severity:.2f}")


def _obedience_score(agent: Agent, act: SpeechAct) -> float:
    social = agent.social_to_player
    score = social.trust + social.affinity * 0.35 - social.fear * 0.45 - social.resentment * 0.35
    score -= agent.needs.stress * 0.18
    if act.force == "order" or act.kind == "order":
        score += 9.0
        if agent.id == "boris":
            score -= 7.0
    if agent.id == "mira":
        score += 8.0
    if agent.id == "alice":
        score += min(10.0, agent.needs.curiosity * 0.08)
    return score


def _object_for_kind(world: WorldState, kind: str) -> WorldObject | None:
    kind = _normalise_object_kind(kind)
    for obj in world.objects.values():
        if obj.kind == kind:
            return obj
    return None


def _should_record_claim(claim: SpeechClaim) -> bool:
    if claim.claim_type in {"player_intention", "player_commitment", "promise", "opinion", "navigation_status", "conversation"}:
        return False
    if claim.subject and _clean_label(claim.subject) in {"player", "you", "self"} and not claim.object:
        return False
    return True


def _normalise_action(value: Any) -> str:
    label = _clean_label(value)
    return ACTION_ALIASES.get(label, label)


def _normalise_object_kind(value: Any) -> str:
    label = _clean_label(value)
    return OBJECT_ALIASES.get(label, label)


def _clean_label(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _unverified_claim_hint(parsed: ParsedSpeech) -> str:
    claims = [claim for claim in parsed.claims if _should_record_claim(claim)]
    if not claims:
        return ""
    claim = claims[0].text
    return f"I only know that you said: {claim}"


def _accept_follow_line(agent: Agent, force: str, claim_hint: str) -> str:
    caveat = f" {claim_hint}" if claim_hint else ""
    if agent.id == "boris":
        return f"Fine. I will follow, but I am watching the supplies and your decisions.{caveat}"
    if agent.id == "mira":
        return f"Okay. I will stay close to you. Please do not make me regret it.{caveat}"
    if force == "order":
        return f"I will follow. But I heard that as an order, not a conversation.{caveat}"
    return f"All right. Lead the way.{caveat}"


def _refuse_follow_line(agent: Agent, claim_hint: str) -> str:
    caveat = f" {claim_hint}" if claim_hint else ""
    if agent.id == "boris":
        return f"No. Not on trust alone. Tell me why first.{caveat}"
    if agent.id == "mira":
        return f"I cannot. Not while everyone is scattered and I am this scared.{caveat}"
    return f"Not yet. I need a better reason.{caveat}"


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
