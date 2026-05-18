from pathlib import Path
from tempfile import TemporaryDirectory

from mozok_game.engine.appraisal import appraise_agent_beliefs
from mozok_game.engine.affordances import build_agent_affordances
from mozok_game.engine.capabilities import execute_item_action
from mozok_game.engine.dialogue_reactions import apply_open_dialogue_reaction, finalise_dialogue_reaction, snapshot_player_relationship
from mozok_game.engine.editor_service import add_object_instance, create_scenario, duplicate_scenario, edit_character_override, move_object_instance, remove_object_instance
from mozok_game.engine.interactions import interact_with_object
from mozok_game.engine.inventory import item_capabilities, transfer_item
from mozok_game.engine.model_settings import GameModelSettings, apply_model_preset, load_game_model_settings, save_game_model_settings
from mozok_game.engine.models import Position, WorldObject
from mozok_game.engine.object_effects import execute_object_interaction
from mozok_game.engine.pack_validation import list_object_templates, spawn_object_instance, validate_appraisal_pack, validate_scenario_pack
from mozok_game.engine.pathfinding import next_step_towards
from mozok_game.engine.relationships import apply_relationship_delta, social_state_for
from mozok_game.engine.scene_context import build_scene_context
from mozok_game.engine.scene_proposal import scene_proposal_from_dict, validate_scene_proposal
from mozok_game.engine.scene_validation import build_scene_grounding, validate_agent_dialogue
from mozok_game.engine.speech_actions import OBJECT_ALIASES, parsed_speech_from_dict
from mozok_game.engine.tick_scheduler import apply_agent_intent, run_agent_ticks
from mozok_game.engine.world_state import load_world, load_world_from_path
from mozok_game.mozok_client import client as client_module
from mozok_game.mozok_client.client import MozokHttpClient
from mozok_game.mozok_client.client import OfflineMozokBrain
from mozok_game.ui.renderer import OBJECT_COLOURS, TILE_COLOURS


def base_dir() -> Path:
    return Path(__file__).resolve().parents[1]


def test_load_world_has_player_agents_objects():
    world = load_world(base_dir())
    assert world.grid.width >= 12
    assert "alice" in world.agents
    assert world.object_by_kind("food_crate") is not None
    assert world.event_log


def test_load_world_from_path_preserves_scenario_metadata_and_aliases():
    path = base_dir() / "data" / "scenarios" / "island_camp_demo.json"
    world = load_world_from_path(base_dir(), path)

    assert world.scenario_id == "island_camp_demo"
    assert world.setting_summary
    assert "mystery" in world.themes
    assert world.grid.tile_defs["grass"]["label"] == "island grass"
    assert "camp knife" in world.objects["knife_01"].aliases


def test_scenario_pack_loader_assembles_map_objects_characters_storylets_and_atoms():
    world = load_world(base_dir())

    assert world.pack_refs["map"] == ["island_camp_01"]
    assert world.pack_refs["objects"] == ["island_survival_objects"]
    assert world.pack_refs["storylets"] == ["storylets"]
    assert world.pack_refs["drama_atoms"] == ["core_atoms"]
    assert world.storylet_specs
    assert world.drama_atoms
    assert world.objects["campfire_01"].kind == "campfire"
    assert world.agents["alice"].position.x == 5


def test_object_template_pack_can_spawn_new_scenario_without_monolithic_objects():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "data" / "maps").mkdir(parents=True)
        (root / "data" / "objects").mkdir(parents=True)
        (root / "data" / "items").mkdir(parents=True)
        (root / "data" / "scenarios").mkdir(parents=True)
        (root / "data" / "storylets").mkdir(parents=True)
        (root / "data" / "drama_atoms").mkdir(parents=True)
        (root / "data" / "items" / "items.json").write_text("{}", encoding="utf-8")
        (root / "data" / "storylets" / "empty.json").write_text("[]", encoding="utf-8")
        (root / "data" / "drama_atoms" / "empty.json").write_text("[]", encoding="utf-8")
        (root / "data" / "maps" / "test_map.json").write_text(
            '{"rows":["...","..."],"legend":{".":{"kind":"floor","walkable":true}},"tile_defs":{"floor":{"label":"test floor","walkable":true}}}',
            encoding="utf-8",
        )
        (root / "data" / "objects" / "test_objects.json").write_text(
            """
            {
              "templates": {
                "rough_bed": {
                  "name": "Rough Bed",
                  "kind": "bed",
                  "object_type": "furniture",
                  "tags": ["rest", "comfort"],
                  "interactions": {
                    "rest": {
                      "label": "Rest",
                      "actor_need_delta": {"fatigue": -10},
                      "message": "{actor} rests at {target}.",
                      "tags": ["rest"]
                    }
                  }
                }
              },
              "instances": [
                {"id": "bed_01", "template_id": "rough_bed", "position": [1, 0], "state": {"made": false}}
              ]
            }
            """,
            encoding="utf-8",
        )
        scenario = root / "data" / "scenarios" / "pack_test.json"
        scenario.write_text(
            """
            {
              "scenario_id": "pack_test",
              "title": "Pack Test",
              "map_ref": "test_map",
              "object_pack_refs": ["test_objects"],
              "item_pack_refs": ["items"],
              "storylet_pack_refs": ["empty"],
              "drama_atom_pack_refs": ["empty"],
              "player": {"position": [0, 0]},
              "agents": [
                {
                  "id": "test_agent",
                  "name": "Test Agent",
                  "role": "tester",
                  "position": [0, 1],
                  "avatar_folder": "mira",
                  "personality": "plain",
                  "traits": {}
                }
              ]
            }
            """,
            encoding="utf-8",
        )

        world = load_world_from_path(root, scenario)

    assert world.scenario_id == "pack_test"
    assert world.grid.tile_defs["floor"]["label"] == "test floor"
    assert world.objects["bed_01"].name == "Rough Bed"
    assert world.objects["bed_01"].state["made"] is False
    assert "rest" in world.objects["bed_01"].interaction_defs


def test_static_island_object_aliases_are_not_runtime_source_of_truth():
    assert OBJECT_ALIASES == {}


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
    assert world.chat_log[-1].speaker_name == "Action"
    assert "Inside: a ration and rope" in world.chat_log[-1].content


def test_object_inspection_feedback_reflects_state_after_pry():
    world = load_world(base_dir())
    knife = world.objects["knife_01"]
    box = world.objects["lockbox_01"]

    interact_with_object(world, box, "inspect")
    before = world.chat_log[-1].content
    interact_with_object(world, knife, "take")
    world.player.position = Position(box.position.x, box.position.y - 1)
    interact_with_object(world, box, "open")
    interact_with_object(world, box, "inspect")
    after = world.chat_log[-1].content

    assert "still locked" in before
    assert "open now" in after


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


def test_data_driven_rest_interaction_supports_custom_bed_without_python_branch():
    world = load_world(base_dir())
    alice = world.agents["alice"]
    alice.needs.fatigue = 82
    alice.needs.stress = 54
    bed = WorldObject(
        id="rough_bed_01",
        name="Rough Bed",
        kind="bed",
        object_type="furniture",
        sprite="objects/rough_bed.png",
        position=Position(alice.position.x + 1, alice.position.y),
        interactions=["rest"],
        tags=["bed", "rest", "shelter", "comfort"],
        interaction_defs={
            "rest": {
                "label": "Rest in bed",
                "primitive": "rest",
                "affordance_tags": ["recover", "fatigue", "comfort"],
                "actor_need_delta": {"fatigue": -35, "stress": -15},
                "event_type": "object_rest",
                "message": "{actor} rests in {target}.",
                "tags": ["rest", "comfort"],
            }
        },
    )
    world.objects[bed.id] = bed

    result = execute_object_interaction(world, alice.id, bed, "rest", "test")

    assert result.ok
    assert alice.needs.fatigue == 47
    assert alice.needs.stress == 39
    assert world.event_log[-1].event_type == "object_rest"


def test_agent_affordances_understand_new_rest_interaction_tags():
    world = load_world(base_dir())
    alice = world.agents["alice"]
    alice.needs.fatigue = 88
    bed = WorldObject(
        id="new_bed_01",
        name="New Bed",
        kind="bed",
        position=Position(alice.position.x + 2, alice.position.y),
        interactions=["rest"],
        tags=["rest", "comfort"],
        interaction_defs={"rest": {"label": "Rest in bed", "primitive": "rest", "affordance_tags": ["recover", "fatigue"], "actor_need_delta": {"fatigue": -30}}},
    )
    world.objects[bed.id] = bed

    affordances = build_agent_affordances(world, alice, world.event_log[-10:])

    assert any(item.parameters.get("object_id") == bed.id and item.parameters.get("interaction_id") == "rest" for item in affordances)


def test_scene_validator_rewrites_unowned_item_stage_direction():
    world = load_world(base_dir())
    alice = world.agents["alice"]
    alice.inventory = []

    result = validate_agent_dialogue(
        world,
        alice,
        "*fidgets with the camp knife, eyes darting to the cave entrance* The clicks are not random.",
    )

    assert "fidgets with the camp knife" not in result.text.lower()
    assert result.rejected_physical_claims


def test_scene_validator_allows_owned_item_stage_direction():
    world = load_world(base_dir())
    alice = world.agents["alice"]
    alice.inventory = ["knife"]

    result = validate_agent_dialogue(world, alice, "*fidgets with the knife* I can keep watch.")

    assert result.text == "*fidgets with the knife* I can keep watch."
    assert not result.rejected_physical_claims


def test_scene_grounding_lists_inventory_and_nearby_interactions():
    world = load_world(base_dir())
    alice = world.agents["alice"]
    alice.inventory.append("knife")

    grounding = build_scene_grounding(world, alice)

    assert "knife" in grounding.inventory
    assert any(item["target_object_id"] for item in grounding.legal_interactions)


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


def test_witnessed_event_creates_agent_belief():
    world = load_world(base_dir())
    alice = world.agents["alice"]
    world.log(
        "item_taken",
        "Player took a ration.",
        tags=["food", "scarcity", "witnessed"],
        actor_id="player",
        target_id="food_crate_01",
        item_id="ration",
        witness_ids=[alice.id],
        visibility="witnessed",
    )

    belief = world.agent_beliefs[-1]
    assert belief.agent_id == alice.id
    assert belief.subject == "player"
    assert belief.object == "ration"
    assert "food" in belief.emotional_tags


def test_scene_context_collects_grounding_beliefs_and_candidate_impulses():
    world = load_world(base_dir())
    alice = world.agents["alice"]
    world.log(
        "mystery_signal",
        "Something clicked near the cave.",
        tags=["mystery", "sound"],
        actor_id="cave_01",
        target_id="alice",
        witness_ids=[alice.id],
        visibility="witnessed",
    )

    context = build_scene_context(world, alice)

    assert context.scenario_id == world.scenario_id
    assert context.visible_objects
    assert context.legal_interactions
    assert context.beliefs
    assert context.appraisals
    assert context.candidate_impulses
    assert context.forbidden_mutations


def test_pack_validation_and_editor_helpers_understand_current_scenario():
    report = validate_scenario_pack(base_dir(), "island_camp_demo")
    templates = list_object_templates(base_dir(), "island_survival_objects")
    instance = spawn_object_instance("campfire", "campfire_copy", (2, 3), {"state": {"lit": True}})

    assert report.ok
    assert "campfire" in templates
    assert instance["template_id"] == "campfire"
    assert instance["state"]["lit"] is True


def test_appraisal_turns_witnessed_resource_belief_into_concern():
    world = load_world(base_dir())
    boris = world.agents["boris"]
    world.log(
        "item_taken",
        "Player took a ration.",
        tags=["food", "scarcity", "witnessed"],
        actor_id="player",
        target_id="food_crate_01",
        item_id="ration",
        witness_ids=[boris.id],
        visibility="witnessed",
    )

    appraisals = appraise_agent_beliefs(world, boris)

    assert appraisals
    assert appraisals[0].concern == "resource_control"
    assert "guard_resource" in appraisals[0].suggested_impulses


def test_structured_scene_proposal_validates_dialogue_and_actions():
    world = load_world(base_dir())
    alice = world.agents["alice"]
    proposal = scene_proposal_from_dict(
        {
            "dialogue": [{"speaker_id": "alice", "text": "*fidgets with the camp knife* I want to check the pattern."}],
            "requested_actions": [
                {"tool_name": "move_to_object", "parameters": {"object_id": "cave_01"}},
                {"tool_name": "use_item_on_target", "parameters": {"item_id": "knife", "target_id": "cave_01", "primitive": "cut"}},
            ],
            "claims": [{"text": "The cave clicks form a pattern.", "truth_status": "unverified", "confidence": 0.45}],
        },
        default_speaker_id=alice.id,
    )

    result = validate_scene_proposal(world, alice, proposal)

    assert "fidgets with the camp knife" not in result.text.lower()
    assert any(action.tool_name == "move_to_object" for action in result.accepted_actions)
    assert result.rejected_actions
    assert result.accepted_claims


def test_loaded_objects_have_render_and_interaction_metadata():
    world = load_world(base_dir())
    campfire = world.objects["campfire_01"]

    assert campfire.object_type == "fixture"
    assert campfire.sprite == "objects/campfire.png"
    assert "rest" in campfire.interaction_defs
    assert campfire.interaction_defs["rest"]["primitive"] == "rest"


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


def test_mozok_client_uses_scenario_id_for_world_and_sessions():
    world = load_world(base_dir())
    client = MozokHttpClient("http://example.test")

    assert client._world_id(world) == world.scenario_id
    assert client._session_id(world, "tick") == f"{world.scenario_id}_tick"


def test_renderer_emergency_fallbacks_are_generic_not_island_vocab():
    assert "grass" not in TILE_COLOURS
    assert "cave" not in TILE_COLOURS
    assert "campfire" not in OBJECT_COLOURS
    assert "food_crate" not in OBJECT_COLOURS


def test_appraisal_rules_load_from_data_pack_and_can_be_overridden():
    report = validate_appraisal_pack(base_dir() / "data" / "appraisals" / "core_appraisals.json")
    world = load_world(base_dir())
    alice = world.agents["alice"]
    world.appraisal_rules = [
        {
            "id": "custom_pressure",
            "concern": "custom_pressure",
            "match_text": ["custom pressure"],
            "base_score": 24,
            "trait_weights": {"curiosity": 10},
            "suggested_impulses": ["investigate"],
        }
    ]
    world.log(
        "custom_event",
        "Player triggered a custom pressure.",
        tags=["custom_pressure"],
        actor_id="player",
        target_id="cave_01",
        witness_ids=[alice.id],
    )

    appraisals = appraise_agent_beliefs(world, alice)

    assert report.ok
    assert appraisals[0].concern == "custom_pressure"


def test_editor_service_crud_helpers_manage_scenario_and_object_pack():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "data" / "scenarios").mkdir(parents=True)
        (root / "data" / "objects").mkdir(parents=True)
        object_pack = {
            "templates": {"bed": {"name": "Bed", "kind": "bed", "interactions": {"rest": {"label": "Rest"}}}},
            "instances": [],
        }
        (root / "data" / "objects" / "test_objects.json").write_text(__import__("json").dumps(object_pack), encoding="utf-8")

        scenario = create_scenario(root, "test_scene", "Test Scene", object_pack_refs=["test_objects"], character_refs=["tester"], overwrite=True)
        duplicate = duplicate_scenario(root, "test_scene", "test_scene_copy", overwrite=True)
        instance = add_object_instance(root, "test_objects", "bed", "bed_01", (2, 3))
        moved = move_object_instance(root, "test_objects", "bed_01", (4, 5))
        override = edit_character_override(root, "test_scene", "tester", {"position": [1, 1]})
        removed = remove_object_instance(root, "test_objects", "bed_01")

        assert scenario["scenario_id"] == "test_scene"
        assert duplicate["scenario_id"] == "test_scene_copy"
        assert instance["id"] == "bed_01"
        assert moved["position"] == [4, 5]
        assert override["overrides"]["position"] == [1, 1]
        assert removed


def test_game_model_settings_are_saved_and_used_by_mozok_client():
    with TemporaryDirectory() as tmp:
        root = Path(tmp)
        settings = GameModelSettings(role_models={"scene": "qwen-scene:latest"}, available_models=["qwen-scene:latest"])
        save_game_model_settings(root, settings)

        loaded = load_game_model_settings(root)
        client = MozokHttpClient("http://example.test", base_dir=root)

    assert loaded.model_for_role("scene") == "qwen-scene:latest"
    assert client._model_hints("chat", "scene")["llm_model"] == "qwen-scene:latest"


def test_mozok_client_limits_expensive_tick_calls_per_turn():
    world = load_world(base_dir())
    alice = world.agents["alice"]
    boris = world.agents["boris"]
    tick_calls: list[str] = []

    class Response:
        status_code = 200
        text = ""

        def json(self):
            return {"selected_action": {"tool_name": "wait", "parameters": {}, "rationale": "test wait"}}

    def fake_post(url, *args, **kwargs):
        if "/agents/" in str(url):
            tick_calls.append(str(url))
        return Response()

    old_post = client_module.requests.post
    try:
        client_module.requests.post = fake_post
        client = MozokHttpClient("http://example.test")
        client.performance.max_llm_ticks_per_turn = 1
        client.performance.llm_tick_cooldown_turns = 0
        first = client.decide(world, alice, world.event_log[-4:])
        second = client.decide(world, boris, world.event_log[-4:])
    finally:
        client_module.requests.post = old_post

    assert first.tool_name == "wait"
    assert len(tick_calls) == 1
    assert "budget" in second.rationale.lower()


def test_semantic_parser_cache_reuses_group_message_parse():
    world = load_world(base_dir())
    alice = world.agents["alice"]
    mira = world.agents["mira"]
    chat_calls: list[str] = []

    class Response:
        status_code = 200
        text = ""

        def json(self):
            return {
                "response": (
                    '{"speech_acts":[{"type":"conversation","action":"none","target":"listener","confidence":0.8}],'
                    '"claims":[],"emotional_tone":"neutral","summary":"cached parse","confidence":0.8}'
                )
            }

    def fake_post(url, *args, **kwargs):
        if str(url).endswith("/chat"):
            chat_calls.append(str(url))
        return Response()

    old_post = client_module.requests.post
    try:
        client_module.requests.post = fake_post
        client = MozokHttpClient("http://example.test")
        first = client.interpret_speech(world, alice, "Stay close and listen.")
        second = client.interpret_speech(world, mira, "Stay close and listen.")
    finally:
        client_module.requests.post = old_post

    assert first.summary == "cached parse"
    assert second.summary == "cached parse"
    assert len(chat_calls) == 1


def test_mozok_client_compacts_known_object_context():
    world = load_world(base_dir())
    client = MozokHttpClient("http://example.test")
    client.performance.known_object_limit = 2
    client.performance.compact_payloads = True

    records = client._visible_object_records(world, agent=world.agents["alice"])

    assert len(records) == 2
    assert all("interactions" in record for record in records)


def test_model_settings_preset_applies_groups_without_losing_manual_control():
    draft = {"chat": "large:latest", "semantic": "small:latest"}

    powerful = apply_model_preset(draft, "reasoner:latest", "powerful")
    helper = apply_model_preset(powerful, "helper:latest", "helper")

    assert powerful["chat"] == "reasoner:latest"
    assert powerful["scene"] == "reasoner:latest"
    assert powerful["reasoning"] == "reasoner:latest"
    assert helper["semantic"] == "helper:latest"
    assert helper["fast"] == "helper:latest"
    assert helper["chat"] == "reasoner:latest"


def test_open_dialogue_reaction_updates_emotion_and_social_feedback():
    world = load_world(base_dir())
    mira = world.agents["mira"]
    before = snapshot_player_relationship(mira)
    parsed = parsed_speech_from_dict("Thank you for helping me.", {"tone": "friendly", "confidence": 0.8})

    apply_open_dialogue_reaction(world, mira, parsed)
    reaction = finalise_dialogue_reaction(world, mira, before, parsed)

    assert reaction.delta["trust"] > 0
    assert reaction.delta["affinity"] > 0
    assert mira.emotion == "happy"
    assert "trust" in reaction.summary


def test_relationship_matrix_tracks_agent_to_agent_state():
    world = load_world(base_dir())
    alice = world.agents["alice"]
    boris = world.agents["boris"]

    apply_relationship_delta(alice, boris.id, {"trust": -6, "resentment": 4})
    social = social_state_for(alice, boris.id)

    assert social.trust == 44
    assert social.resentment == 9
    assert social_state_for(alice, "player") is alice.social_to_player
