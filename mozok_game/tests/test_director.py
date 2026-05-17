from pathlib import Path

from mozok_game.engine.director import apply_dialogue_choice, build_dialogue_options, run_social_director, trigger_scripted_moment
from mozok_game.engine.affordances import choose_offline_intent
from mozok_game.engine.commitments import sync_legacy_commitment_cache
from mozok_game.engine.impulses import generate_impulses
from mozok_game.engine.models import Agent, Commitment, Needs, Position, SocialState, WorldObject
from mozok_game.engine.speech_actions import apply_agent_decision, decide_agent_response, fallback_interpret_player_speech, parsed_speech_from_dict, record_player_claims
from mozok_game.engine.storylets import run_storylet_director
from mozok_game.engine.tick_scheduler import _apply_player_commitment, apply_agent_intent, run_agent_ticks
from mozok_game.engine.world_state import load_world
from mozok_game.mozok_client.client import OfflineMozokBrain


def base_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def test_dialogue_choice_surfaces_memory_flash():
    world = load_world(base_dir())
    alice = world.agents["alice"]

    options = build_dialogue_options(world, alice)
    apply_dialogue_choice(world, alice, options[0]["id"])

    assert alice.last_dialogue
    assert world.brain_flashes
    assert world.brain_flashes[-1].agent_id == "alice"


def test_food_scripted_moment_marks_generic_controller_supply_pressure():
    world = load_world(base_dir())
    controller = Agent(
        id="generated_controller",
        name="Rhea",
        role="controller",
        position=Position(5, 5),
        avatar_folder="mira",
        personality="Cautious and controlling.",
        traits={"dominance": 0.85, "caution": 0.75},
        social_to_player=SocialState(trust=36, fear=10, affinity=20, resentment=30),
    )
    world.agents = {controller.id: controller}

    trigger_scripted_moment(world, "food_taken")

    assert controller.social_to_player.resentment > 30
    assert any(flash.agent_id == controller.id for flash in world.brain_flashes)


def test_social_director_adds_agent_dialogue_when_agents_are_near():
    world = load_world(base_dir())

    run_social_director(world)

    assert world.last_agent_conversation_turn == world.turn
    assert world.event_log[-1].event_type == "agent_agent_dialogue"


def test_social_director_uses_scene_weaver_before_dialogue_pack_fallback():
    world = load_world(base_dir())

    def scene_weaver(world, speaker, listener, motive):
        return f"{speaker.name}: This line came from the scene weaver."

    run_social_director(world, scene_weaver=scene_weaver)

    assert world.chat_log[-1].content == "This line came from the scene weaver."
    assert world.event_log[-1].content.endswith("This line came from the scene weaver.")


def test_offline_group_chat_records_agent_reply():
    world = load_world(base_dir())
    alice = world.agents["alice"]
    brain = OfflineMozokBrain()

    world.chat("player", "You", "What do you think about the cave?", source="player")
    reply = brain.chat(world, alice, "What do you think about the cave?", ["Alice", "Mira"])
    world.chat(alice.id, alice.name, reply, source="agent")

    assert reply
    assert world.chat_log[-1].speaker_id == "alice"
    assert "Alice" in alice.last_dialogue


def test_follow_request_creates_agent_commitment():
    world = load_world(base_dir())
    mira = world.agents["mira"]

    speech = fallback_interpret_player_speech("Please follow me and stay close.")
    decision = decide_agent_response(world, mira, speech)
    apply_agent_decision(world, mira, speech, decision)

    assert decision.accepted
    assert mira.following_player
    assert mira.active_commitment is not None
    assert mira.active_commitment.type == "follow"
    assert mira.brain_focus == "Following the player by choice."


def test_hostile_speech_changes_social_state_without_combat():
    world = load_world(base_dir())
    boris = world.agents["boris"]
    before_fear = boris.social_to_player.fear

    speech = fallback_interpret_player_speech("I will fight you.")
    decision = decide_agent_response(world, boris, speech)
    apply_agent_decision(world, boris, speech, decision)

    assert decision.action == "hostile_alarm"
    assert not decision.accepted
    assert boris.social_to_player.fear > before_fear


def test_semantic_parser_output_drives_threat_without_keywords():
    world = load_world(base_dir())
    boris = world.agents["boris"]
    parsed = parsed_speech_from_dict(
        "I'm gonna smash your face.",
        {
            "speech_acts": [
                {
                    "type": "threat",
                    "action": "threaten_actor",
                    "target": "listener",
                    "severity": 0.86,
                    "confidence": 0.94,
                    "rationale": "idiomatic physical intimidation",
                }
            ],
            "emotional_tone": "hostile",
            "confidence": 0.94,
        },
    )

    decision = decide_agent_response(world, boris, parsed)

    assert decision.action == "hostile_alarm"
    assert "threat" in decision.reason


def test_player_claims_are_recorded_as_unverified():
    world = load_world(base_dir())
    mira = world.agents["mira"]
    parsed = parsed_speech_from_dict(
        "I heard someone crying in the cave. Follow me.",
        {
            "speech_acts": [{"type": "request", "action": "follow_player", "confidence": 0.9}],
            "claims": [{"text": "The player heard someone crying in the cave.", "object_kind": "cave_entrance", "confidence": 0.75}],
        },
    )

    record_player_claims(world, mira, parsed)

    assert world.claim_log[-1].listener_id == "mira"
    assert world.claim_log[-1].truth_status == "unverified"
    assert world.claim_log[-1].target_object_id == "cave_01"


def test_player_following_agent_is_not_recorded_as_suspicious_claim():
    world = load_world(base_dir())
    mira = world.agents["mira"]
    cave = world.objects["cave_01"]
    go_parsed = parsed_speech_from_dict(
        "Please check the cave.",
        {"speech_acts": [{"type": "request", "action": "go_to_object", "object_kind": "cave_entrance", "confidence": 0.9}]},
    )
    go_decision = decide_agent_response(world, mira, go_parsed)
    apply_agent_decision(world, mira, go_parsed, go_decision)

    parsed = parsed_speech_from_dict(
        "Okay, I am going after you.",
        {
            "speech_acts": [{"type": "promise", "action": "player_follow_agent", "confidence": 0.92}],
            "claims": [{"text": "The player is following Mira.", "claim_type": "player_intention", "confidence": 0.9}],
        },
    )

    record_player_claims(world, mira, parsed)
    decision = decide_agent_response(world, mira, parsed)
    apply_agent_decision(world, mira, parsed, decision)

    assert not world.claim_log
    assert decision.action == "acknowledge_player_commitment"
    assert mira.command_target_object_id == cave.id
    assert mira.active_commitment is not None
    assert "Cave Entrance" in decision.reply


def test_semantic_target_object_id_drives_destination_without_kind_alias():
    world = load_world(base_dir())
    mira = world.agents["mira"]
    parsed = parsed_speech_from_dict(
        "Please check that exact place.",
        {"speech_acts": [{"type": "request", "action": "go_to_object", "target_object_id": "spring_01", "confidence": 0.9}]},
    )

    decision = decide_agent_response(world, mira, parsed)

    assert decision.handled
    assert decision.target_object_id == "spring_01"


def test_semantic_object_labels_can_target_new_object_without_static_alias():
    world = load_world(base_dir())
    mira = world.agents["mira"]
    world.objects["cot_01"] = WorldObject(
        id="cot_01",
        name="Recovery Cot",
        kind="portable_bed",
        object_type="furniture",
        position=Position(6, 5),
        tags=["rest", "comfort", "medical"],
        interactions=["rest"],
        interaction_defs={
            "rest": {
                "label": "Rest on recovery cot",
                "primitive": "rest",
                "affordance_tags": ["recover", "fatigue", "comfort"],
                "actor_need_delta": {"fatigue": -30},
            }
        },
    )
    parsed = parsed_speech_from_dict(
        "Please go check the cot.",
        {"speech_acts": [{"type": "request", "action": "go_to_object", "object_kind": "cot", "confidence": 0.9}]},
    )

    decision = decide_agent_response(world, mira, parsed)

    assert decision.handled
    assert decision.target_object_id == "cot_01"


def test_commitment_expiry_clears_legacy_cache():
    world = load_world(base_dir())
    mira = world.agents["mira"]
    mira.active_commitment = Commitment(
        id="commit_test_expire",
        agent_id=mira.id,
        type="inspect",
        target_object_id="cave_01",
        goal="inspect cave entrance",
        expiry_turns=1,
        started_turn=0,
        accepted_because="test",
    )
    sync_legacy_commitment_cache(mira)
    assert mira.command_target_object_id == "cave_01"

    world.turn = 3
    handled = _apply_player_commitment(world, mira.id)

    assert not handled
    assert mira.active_commitment is None
    assert not mira.following_player
    assert mira.command_target_object_id == ""
    assert mira.commitment_history[-1].status == "expired"


def test_commitment_constraint_interrupt_clears_legacy_cache():
    world = load_world(base_dir())
    mira = world.agents["mira"]
    mira.health = 30
    mira.active_commitment = Commitment(
        id="commit_test_interrupt",
        agent_id=mira.id,
        type="inspect",
        target_object_id="cave_01",
        goal="inspect cave entrance",
        constraints={"avoid_if_health_below": 45},
        started_turn=world.turn,
        accepted_because="test",
    )
    sync_legacy_commitment_cache(mira)

    handled = _apply_player_commitment(world, mira.id)

    assert not handled
    assert mira.active_commitment is None
    assert not mira.following_player
    assert mira.command_target_object_id == ""
    assert mira.commitment_history[-1].status == "interrupted"


def test_unverified_claim_becomes_deliberation_affordance():
    world = load_world(base_dir())
    alice = world.agents["alice"]
    world.claim("player", "alice", "I heard someone crying in the cave.", confidence=0.8)

    intent = choose_offline_intent(world, alice, world.event_log[-10:])

    assert intent.tool_name in {"talk_to_player", "move_to_object"}
    assert "unverified claim" in intent.rationale
    assert "Candidates:" in alice.deliberation_summary


def test_talk_to_agent_intent_creates_agent_conversation():
    world = load_world(base_dir())
    alice = world.agents["alice"]
    boris = world.agents["boris"]
    boris.position = Position(alice.position.x + 1, alice.position.y)

    apply_agent_intent(
        world,
        alice.id,
        "talk_to_agent",
        {"target_agent_id": boris.id},
        dialogue="Alice: Boris, listen before we split up.",
        rationale="social pressure needs coordination",
    )

    assert world.chat_log[-1].speaker_id == "alice"
    assert world.event_log[-1].event_type == "agent_agent_dialogue"
    assert world.event_log[-1].metadata["listener_id"] == "boris"


def test_storylet_director_uses_pressure_not_fixed_turn():
    world = load_world(base_dir())
    world.turn = 6

    run_agent_ticks(world, OfflineMozokBrain())

    assert "rain_squall" in world.scripted_flags
    assert any(event.event_type == "weather_rain_squall" for event in world.event_log)
    assert world.pressure["exhaustion"] > 0


def test_storylet_director_scores_eligible_storylets_instead_of_first_match():
    world = load_world(base_dir())
    world.turn = 3
    world.storylet_specs = [
        {
            "id": "low_weight",
            "title": "Low Weight",
            "tags": ["mystery"],
            "weight": 0.1,
            "requires": {"turn_gte": 1},
            "effects": [{"type": "log", "event_type": "low_weight_event", "message": "Low weight fired."}],
        },
        {
            "id": "high_weight",
            "title": "High Weight",
            "tags": ["mystery"],
            "weight": 2.0,
            "requires": {"turn_gte": 1},
            "effects": [{"type": "log", "event_type": "high_weight_event", "message": "High weight fired."}],
        },
    ]

    run_storylet_director(world)

    assert "high_weight" in world.scripted_flags
    assert world.event_log[-1].event_type == "high_weight_event"


def test_storylet_director_prefers_recovery_when_chaos_is_high():
    world = load_world(base_dir())
    world.turn = 8
    world.pressure.update({"danger": 0.9, "instability": 0.8, "moral_pressure": 0.75, "exhaustion": 0.9, "scarcity": 0.8})
    world.storylet_specs = [
        {
            "id": "more_pressure",
            "title": "More Pressure",
            "pacing_category": "pressure",
            "weight": 1.0,
            "requires": {"turn_gte": 1},
            "effects": [{"type": "log", "event_type": "pressure_event", "message": "Pressure fired."}],
        },
        {
            "id": "recovery",
            "title": "Recovery",
            "pacing_category": "recovery",
            "weight": 0.5,
            "requires": {"turn_gte": 1},
            "effects": [{"type": "log", "event_type": "recovery_event", "message": "Recovery fired."}],
        },
    ]

    run_storylet_director(world)

    assert "recovery" in world.scripted_flags
    assert world.event_log[-1].event_type == "recovery_event"


def test_storylet_requirements_can_use_beliefs_and_object_state():
    world = load_world(base_dir())
    alice = world.agents["alice"]
    world.objects["cave_01"].state["marked"] = True
    world.log(
        "mystery_signal",
        "Alice saw the cave mark change.",
        tags=["mystery"],
        actor_id="cave_01",
        target_id="alice",
        witness_ids=[alice.id],
        visibility="witnessed",
    )
    world.storylet_specs = [
        {
            "id": "belief_gate",
            "title": "Belief Gate",
            "requires": {
                "requires_agent_belief": {"agent_id": alice.id, "emotional_tags": ["mystery"]},
                "requires_object_state": {"id": "cave_01", "state": {"marked": True}},
            },
            "effects": [{"type": "create_goal", "select_agent": alice.id, "goal": "investigate_marked_place"}],
        }
    ]

    run_storylet_director(world)

    assert alice.current_goal == "investigate_marked_place"


def test_dominant_low_trust_generic_agent_generates_resource_impulse_without_boris_id():
    world = load_world(base_dir())
    agent = Agent(
        id="random_survivor_42",
        name="Rhea",
        role="generated survivor",
        position=Position(6, 5),
        avatar_folder="mira",
        personality="Cautious, controlling, low-trust survivor.",
        traits={"dominance": 0.82, "caution": 0.74, "agreeableness": 0.22, "empathy": 0.31},
        values=["survival", "control"],
        fears=["starvation"],
        needs=Needs(hunger=58, thirst=30, fatigue=20, stress=32, social=30, curiosity=18),
        social_to_player=SocialState(trust=20, fear=12, affinity=18, resentment=45),
    )
    world.agents = {agent.id: agent}
    world.log(
        "item_taken",
        "Player took food.",
        tags=["food", "scarce", "witnessed"],
        actor_id="player",
        target_id="food_crate_01",
        item_id="ration",
        visibility="witnessed",
    )

    impulses = generate_impulses(world, agent, world.event_log[-10:])

    assert any(impulse.kind in {"demand", "guard_resource"} for impulse in impulses)
