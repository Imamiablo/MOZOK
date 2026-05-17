from pathlib import Path

from mozok_game.engine.capabilities import execute_item_action
from mozok_game.engine.interactions import interact_with_object
from mozok_game.engine.inventory import item_capabilities, transfer_item
from mozok_game.engine.models import Position, WorldObject
from mozok_game.engine.pathfinding import next_step_towards
from mozok_game.engine.tick_scheduler import apply_agent_intent, run_agent_ticks
from mozok_game.engine.world_state import load_world
from mozok_game.mozok_client import client as client_module
from mozok_game.mozok_client.client import MozokHttpClient
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
    world.player.position = Position(box.position.x, box.position.y - 1)
    interact_with_object(world, box)

    assert "knife" in world.player.inventory
    assert "ration" in world.player.inventory
    assert "rope" in world.player.inventory
    assert box.state["open"]
    assert world.event_log[-1].event_type == "item_action_pry"


def test_item_capability_can_anchor_rope_at_cave():
    world = load_world(base_dir())
    cave = world.objects["cave_01"]
    world.player.position = Position(cave.position.x, cave.position.y - 1)
    world.player.inventory.append("rope")

    result = execute_item_action(world, "player", "rope", cave.id, "anchor", "test")

    assert result.ok
    assert cave.state["rope_anchored"]
    assert "rope" not in world.player.inventory


def test_item_definitions_are_loaded_from_data_file():
    assert "anchor" in item_capabilities("rope")
    assert "pry" in item_capabilities("knife")


def test_data_driven_target_effect_supports_new_object_without_python_branch():
    world = load_world(base_dir())
    anchor = WorldObject(
        id="test_anchor_01",
        name="Test Anchor",
        kind="custom_anchor",
        position=Position(world.player.position.x, world.player.position.y + 1),
        interactions=["inspect"],
        tags=["tool", "safety"],
        capability_accepts=["anchor"],
        capability_effects={
            "anchor": {
                "message": "{actor} anchors {item} to {target}.",
                "tags": ["item", "capability", "anchor", "custom"],
                "target_state": {"secured": True, "secured_by": "{actor_id}"},
                "consume_item": True,
            }
        },
    )
    world.objects[anchor.id] = anchor
    world.player.inventory.append("rope")

    result = execute_item_action(world, "player", "rope", anchor.id, "anchor", "test")

    assert result.ok
    assert anchor.state["secured"] is True
    assert anchor.state["secured_by"] == "player"
    assert "rope" not in world.player.inventory


def test_invalid_item_capability_is_rejected():
    world = load_world(base_dir())
    cave = world.objects["cave_01"]
    world.player.position = Position(cave.position.x, cave.position.y - 1)
    world.player.inventory.append("ration")

    result = execute_item_action(world, "player", "ration", cave.id, "anchor", "test")

    assert not result.ok
    assert world.event_log[-1].event_type == "item_action_rejected"
    assert world.event_log[-1].actor_id == "player"


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


def test_agent_can_use_capability_tool_on_target():
    world = load_world(base_dir())
    boris = world.agents["boris"]
    box = world.objects["lockbox_01"]
    boris.position = Position(box.position.x, box.position.y - 1)

    apply_agent_intent(world, boris.id, "use_item_on_target", {"item_id": "knife", "target_id": box.id, "primitive": "pry"}, rationale="test")

    assert box.state["open"]
    assert "ration" in boris.inventory


def test_world_events_have_structured_actor_target_item_and_witnesses():
    world = load_world(base_dir())
    event = world.log(
        "item_taken",
        "Player took a ration.",
        tags=["food", "scarce", "witnessed"],
        actor_id="player",
        target_id="food_crate_01",
        item_id="ration",
        visibility="witnessed",
    )

    assert event.event_id.startswith("evt_")
    assert event.actor_id == "player"
    assert event.target_id == "food_crate_01"
    assert event.item_id == "ration"
    assert event.visibility == "witnessed"
    assert event.witness_ids


def test_world_events_have_truth_status_and_idempotency_key():
    world = load_world(base_dir())

    event = world.log(
        "claim_test",
        "A test event happened once.",
        actor_id="player",
        target_id="food_crate_01",
        truth_status="verified",
        idempotency_key="global:item_taken:food_crate_01:1",
    )

    assert event.truth_status == "verified"
    assert event.idempotency_key == "global:item_taken:food_crate_01:1"
    assert event.metadata["idempotency_key"] == event.idempotency_key


def test_pressure_field_is_bounded_and_quiet_axes_decay():
    world = load_world(base_dir())
    world.pressure["danger"] = 0.99
    world.pressure["scarcity"] = 0.5

    for _ in range(30):
        world.log("danger_test", "The situation is dangerous.", salience=10, tags=["danger"])

    assert all(0.0 <= value <= 1.0 for value in world.pressure.values())
    before = world.pressure["scarcity"]
    world.log("quiet_test", "Nothing much happens.", salience=1, tags=[])
    assert world.pressure["scarcity"] < before


def test_mozok_event_post_uses_world_event_and_perception_ids_once():
    world = load_world(base_dir())
    agent = world.agents["alice"]
    event = world.log("item_taken", "Player took a ration.", actor_id="player", item_id="ration", idempotency_key="global:item:1")
    calls = []

    class Response:
        status_code = 200
        text = ""

    old_post = client_module.requests.post
    try:
        client_module.requests.post = lambda *args, **kwargs: calls.append(kwargs["json"]) or Response()
        client = MozokHttpClient("http://example.test")
        client._post_world_event(world, agent, event)
        client._post_world_event(world, agent, event)
    finally:
        client_module.requests.post = old_post

    assert len(calls) == 1
    payload_event = calls[0]["events"][0]
    assert payload_event["world_event_id"] == event.event_id
    assert payload_event["perception_id"] == f"{agent.id}:{event.event_id}"
    assert payload_event["idempotency_key"] == "global:item:1"
