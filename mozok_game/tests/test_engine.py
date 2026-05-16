from pathlib import Path

from mozok_game.engine.interactions import interact_with_object
from mozok_game.engine.inventory import transfer_item
from mozok_game.engine.models import Position
from mozok_game.engine.pathfinding import next_step_towards
from mozok_game.engine.tick_scheduler import apply_agent_intent, run_agent_ticks
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


def test_player_can_pick_up_item_and_open_lockbox_with_tool():
    world = load_world(base_dir())
    knife = world.objects["knife_01"]
    box = world.objects["lockbox_01"]

    interact_with_object(world, knife)
    interact_with_object(world, box)

    assert "knife" in world.player.inventory
    assert "ration" in world.player.inventory
    assert "rope" in world.player.inventory
    assert box.state["open"]


def test_inventory_transfer_between_player_and_agent():
    world = load_world(base_dir())
    alice = world.agents["alice"]
    world.player.inventory.append("medkit")

    assert transfer_item(world, "player", alice.id, "medkit", "test")
    assert "medkit" in alice.inventory
    assert "medkit" not in world.player.inventory


def test_agent_uses_medkit_when_wounded():
    world = load_world(base_dir())
    mira = world.agents["mira"]
    mira.inventory.append("medkit")
    mira.health = 60
    assert "wounded" in mira.status_flags

    apply_agent_intent(world, mira.id, "use_inventory_item", {"item_id": "medkit"}, rationale="test")

    assert "medkit" not in mira.inventory
    assert mira.health > 60


def test_agent_can_give_item_to_wounded_neighbour():
    world = load_world(base_dir())
    boris = world.agents["boris"]
    mira = world.agents["mira"]
    boris.inventory.append("medkit")
    mira.position = Position(boris.position.x + 1, boris.position.y)

    apply_agent_intent(world, boris.id, "give_item", {"target_agent_id": mira.id, "item_id": "medkit"}, rationale="test")

    assert "medkit" not in boris.inventory
    assert mira.health > 68
