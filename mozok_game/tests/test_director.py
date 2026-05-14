from pathlib import Path

from mozok_game.engine.director import apply_dialogue_choice, build_dialogue_options, run_social_director, trigger_scripted_moment
from mozok_game.engine.world_state import load_world


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


def test_food_scripted_moment_marks_boris_supply_pressure():
    world = load_world(base_dir())

    trigger_scripted_moment(world, "food_taken")

    boris = world.agents["boris"]
    assert boris.social_to_player.resentment > 18
    assert any(flash.agent_id == "boris" for flash in world.brain_flashes)


def test_social_director_adds_agent_dialogue_when_agents_are_near():
    world = load_world(base_dir())

    run_social_director(world)

    assert world.last_agent_conversation_turn == world.turn
    assert world.event_log[-1].event_type == "agent_agent_dialogue"
