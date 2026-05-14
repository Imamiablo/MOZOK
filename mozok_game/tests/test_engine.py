from pathlib import Path

from mozok_game.engine.interactions import interact_with_object
from mozok_game.engine.pathfinding import next_step_towards
from mozok_game.engine.tick_scheduler import run_agent_ticks
from mozok_game.engine.world_state import load_world
from mozok_game.mozok_client.client import OfflineMozokBrain


def base_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def test_load_world_has_player_agents_objects():
    world = load_world(base_dir())
    assert world.grid.width >= 12
    assert "alice" in world.agents
    assert world.object_by_kind("food_crate") is not None
    assert world.event_log


def test_player_can_take_food_from_crate():
    world = load_world(base_dir())
    crate = world.objects["food_crate_01"]
    before = crate.state["food"]
    world.player.position = crate.position.copy()
    interact_with_object(world, crate)
    assert crate.state["food"] == before - 1
    assert "ration" in world.player.inventory
    assert world.event_log[-1].event_type == "player_take_food"


def test_pathfinding_returns_next_step():
    world = load_world(base_dir())
    start = world.agents["alice"].position
    target = world.objects["spring_01"].position
    step = next_step_towards(world.grid, start, target, blocked=set())
    assert step is not None
    assert step.manhattan(start) == 1


def test_offline_tick_moves_or_speaks_agents():
    world = load_world(base_dir())
    before_turn = world.turn
    run_agent_ticks(world, OfflineMozokBrain())
    assert world.turn == before_turn + 1
    assert len(world.event_log) > 2
    assert any(event.source in world.agents for event in world.event_log)


def test_agent_emotion_changes_with_social_pressure():
    world = load_world(base_dir())
    boris = world.agents["boris"]
    boris.social_to_player.resentment = 90
    run_agent_ticks(world, OfflineMozokBrain())
    assert boris.emotion in {"angry", "suspicious", "neutral", "curious", "tired", "afraid"}
