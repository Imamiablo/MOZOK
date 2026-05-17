from __future__ import annotations

from mozok_game.engine.models import Agent


def sync_legacy_commitment_cache(agent: Agent) -> None:
    commitment = agent.active_commitment
    if not commitment or commitment.status != "active":
        clear_legacy_commitment_cache(agent)
        return
    agent.following_player = commitment.type == "follow"
    agent.command_target_object_id = "" if commitment.type == "follow" else commitment.target_object_id
    agent.command_reason = commitment.accepted_because or commitment.goal
    agent.command_source = commitment.issuer_id
    agent.command_priority = commitment.priority
    agent.command_started_turn = commitment.started_turn
    agent.command_interrupt_reason = ""


def clear_legacy_commitment_cache(agent: Agent, *, keep_hold: bool = False) -> None:
    agent.following_player = False
    agent.command_target_object_id = ""
    agent.command_reason = ""
    agent.command_priority = 0.0
    agent.command_started_turn = 0
    if not keep_hold:
        agent.command_hold_turns = 0
