from __future__ import annotations

import os
from pathlib import Path

from mozok_game.engine.dialogue_reactions import apply_open_dialogue_reaction, finalise_dialogue_reaction, snapshot_player_relationship
from mozok_game.engine.director import apply_dialogue_choice, build_dialogue_options
from mozok_game.engine.interactions import interact_with_object
from mozok_game.engine.inventory import first_transferable_item, item_name, transfer_item
from mozok_game.engine.model_settings import MODEL_ROLES, apply_model_preset, discover_ollama_models, load_game_model_settings, merge_discovered_models, save_game_model_settings
from mozok_game.engine.object_effects import interaction_spec
from mozok_game.engine.scene_validation import validate_agent_dialogue
from mozok_game.engine.speech_actions import apply_agent_decision, decide_agent_response, record_player_claims
from mozok_game.engine.tick_scheduler import apply_agent_intent, run_agent_ticks
from mozok_game.engine.world_state import WorldState, load_world
from mozok_game.mozok_client.client import build_brain_client
from mozok_game.ui.renderer import Renderer


FACING_ORDER = ["north", "east", "south", "west"]
FACING_DELTAS = {
    "north": (0, -1),
    "east": (1, 0),
    "south": (0, 1),
    "west": (-1, 0),
}


class PygameApp:
    def __init__(self, base_dir: Path) -> None:
        import pygame

        self.pygame = pygame
        self.base_dir = base_dir
        pygame.init()
        self.world: WorldState = load_world(base_dir, os.getenv("MOZOK_GAME_SCENARIO_ID", "island_camp_demo"))
        self.brain = build_brain_client(base_dir)
        self.dialogue_menu: dict | None = None
        self.object_menu: dict | None = None
        self.text_chat: dict | None = None
        self.agent_dossier: dict | None = None
        self.model_settings = load_game_model_settings(base_dir)
        self.model_settings_ui: dict | None = None
        self.last_auto_chat_event_id: str = ""
        self.world.log("brain_mode", getattr(self.brain, "last_status", "Brain client ready"), source="game", salience=4, tags=["debug", "brain"])
        width = 1280
        height = 720
        self.screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption(f"MOZOK: {self.world.scenario_title} - First Person Prototype")
        self.clock = pygame.time.Clock()
        self.renderer = Renderer(pygame, self.screen, base_dir)

    def run(self) -> None:
        running = True
        while running:
            for event in self.pygame.event.get():
                if event.type == self.pygame.QUIT:
                    running = False
                elif event.type == self.pygame.TEXTINPUT and self.model_settings_ui and self.model_settings_ui.get("editing"):
                    self._handle_model_settings_text(event.text)
                elif event.type == self.pygame.TEXTINPUT and self.text_chat:
                    self.text_chat["text"] += event.text
                elif event.type == self.pygame.MOUSEWHEEL and self.text_chat:
                    self._scroll_text_chat(event.y * 3)
                elif event.type == self.pygame.KEYDOWN:
                    running = self._handle_key(event.key)
            self.renderer.draw(self.world, self.dialogue_menu, self.text_chat, self.agent_dossier, self.object_menu, self.model_settings_ui)
            self.clock.tick(30)
        self.pygame.quit()

    def _handle_key(self, key: int) -> bool:
        pg = self.pygame
        if self.model_settings_ui:
            return self._handle_model_settings_key(key)
        if self.text_chat:
            return self._handle_text_chat_key(key)
        if self.agent_dossier:
            return self._handle_dossier_key(key)
        if self.object_menu:
            return self._handle_object_menu_key(key)
        if self.dialogue_menu:
            return self._handle_dialogue_key(key)
        if key == pg.K_ESCAPE:
            return False
        if key == pg.K_TAB:
            self.renderer.cycle_bottom_tab()
            return True
        if key == pg.K_F3:
            self.renderer.debug = not self.renderer.debug
            return True
        if key in {pg.K_m}:
            self._open_model_settings()
            return True
        if key in {pg.K_i}:
            self._open_agent_dossier()
            return True
        if key in {pg.K_SPACE}:
            self.world.log("player_wait", "You wait and listen.", tags=["wait"])
            run_agent_ticks(self.world, self.brain)
            self._maybe_open_initiated_chat()
            return True
        if key in {pg.K_e}:
            if self._interact():
                run_agent_ticks(self.world, self.brain)
            return True
        if key in {pg.K_t}:
            self._open_text_chat()
            return True
        if key in {pg.K_g}:
            self._give_item_to_front_agent()
            return True
        if key in {pg.K_r}:
            self._request_item_from_front_agent()
            return True
        if key in {pg.K_LEFT, pg.K_a}:
            self._rotate_player(-1)
            return True
        if key in {pg.K_RIGHT, pg.K_d}:
            self._rotate_player(1)
            return True
        if key in {pg.K_UP, pg.K_w}:
            self._move_relative(1)
            run_agent_ticks(self.world, self.brain)
            self._maybe_open_initiated_chat()
            return True
        if key in {pg.K_DOWN, pg.K_s}:
            self._move_relative(-1)
            run_agent_ticks(self.world, self.brain)
            self._maybe_open_initiated_chat()
            return True
        return True

    def _handle_dossier_key(self, key: int) -> bool:
        pg = self.pygame
        if key in {pg.K_ESCAPE, pg.K_i}:
            self.agent_dossier = None
            return True
        if key in {pg.K_DOWN, pg.K_PAGEDOWN, pg.K_s}:
            self.agent_dossier["scroll"] = int(self.agent_dossier.get("scroll", 0)) + (8 if key == pg.K_PAGEDOWN else 1)
            return True
        if key in {pg.K_UP, pg.K_PAGEUP, pg.K_w}:
            self.agent_dossier["scroll"] = max(0, int(self.agent_dossier.get("scroll", 0)) - (8 if key == pg.K_PAGEUP else 1))
            return True
        return True

    def _rotate_player(self, direction: int) -> None:
        index = FACING_ORDER.index(self.world.player_facing)
        self.world.player_facing = FACING_ORDER[(index + direction) % len(FACING_ORDER)]
        self.world.log("player_turn", f"You turn {self.world.player_facing}.", tags=["movement", "turn"])

    def _move_relative(self, amount: int) -> None:
        dx, dy = FACING_DELTAS[self.world.player_facing]
        self._move_player(dx * amount, dy * amount)

    def _move_player(self, dx: int, dy: int) -> None:
        from mozok_game.engine.models import Position

        new = Position(self.world.player.position.x + dx, self.world.player.position.y + dy)
        occupied = {(a.position.x, a.position.y) for a in self.world.agents.values() if a.alive}
        if not self.world.grid.is_walkable(new):
            self.world.log("player_bump", "You cannot go that way.", tags=["movement", "blocked"])
            return
        if (new.x, new.y) in occupied:
            self.world.log("player_bump_agent", "Someone is standing there.", tags=["movement", "agent"])
            return
        self.world.player.position = new
        self.world.player.hunger += 0.5
        self.world.player.thirst += 0.8
        self.world.log("player_move", f"You move to {new.x},{new.y}.", tags=["movement"])

    def _handle_dialogue_key(self, key: int) -> bool:
        pg = self.pygame
        if key in {pg.K_ESCAPE, pg.K_t}:
            self.dialogue_menu = None
            return True
        key_to_index = {
            pg.K_1: 0,
            pg.K_KP1: 0,
            pg.K_2: 1,
            pg.K_KP2: 1,
            pg.K_3: 2,
            pg.K_KP3: 2,
        }
        if key not in key_to_index:
            return True
        index = key_to_index[key]
        options = self.dialogue_menu.get("options", [])
        if index >= len(options):
            return True
        agent = self.world.agents.get(self.dialogue_menu["agent_id"])
        if not agent:
            self.dialogue_menu = None
            return True
        apply_dialogue_choice(self.world, agent, options[index]["id"])
        self.dialogue_menu = None
        run_agent_ticks(self.world, self.brain)
        return True

    def _handle_object_menu_key(self, key: int) -> bool:
        pg = self.pygame
        if key in {pg.K_ESCAPE, pg.K_e}:
            self.object_menu = None
            return True
        keys = [pg.K_1, pg.K_2, pg.K_3, pg.K_4, pg.K_5, pg.K_6, pg.K_7, pg.K_8, pg.K_9]
        keypad = [pg.K_KP1, pg.K_KP2, pg.K_KP3, pg.K_KP4, pg.K_KP5, pg.K_KP6, pg.K_KP7, pg.K_KP8, pg.K_KP9]
        if key not in keys and key not in keypad:
            return True
        index = (keys.index(key) if key in keys else keypad.index(key))
        obj = self.world.objects.get(str(self.object_menu.get("object_id", "")))
        options = list(self.object_menu.get("options", []))
        if not obj or index >= len(options):
            return True
        interaction_id = str(options[index].get("id") or "")
        self.object_menu = None
        interact_with_object(self.world, obj, interaction_id)
        run_agent_ticks(self.world, self.brain)
        self._maybe_open_initiated_chat()
        return True

    def _handle_text_chat_key(self, key: int) -> bool:
        pg = self.pygame
        if key == pg.K_ESCAPE:
            self.text_chat = None
            return True
        if key == pg.K_BACKSPACE:
            self.text_chat["text"] = self.text_chat["text"][:-1]
            return True
        if key in {pg.K_UP, pg.K_PAGEUP}:
            self._scroll_text_chat(9 if key == pg.K_PAGEUP else 1)
            return True
        if key in {pg.K_DOWN, pg.K_PAGEDOWN}:
            self._scroll_text_chat(-9 if key == pg.K_PAGEDOWN else -1)
            return True
        if key == pg.K_HOME:
            self.text_chat["scroll"] = 9999
            return True
        if key == pg.K_END:
            self.text_chat["scroll"] = 0
            return True
        if key == pg.K_RETURN:
            text = self.text_chat.get("text", "").strip()
            targets = list(self.text_chat.get("target_ids", []))
            if text and targets:
                self._send_group_chat(text, targets)
                self.text_chat["text"] = ""
                self.text_chat["scroll"] = 0
            return True
        return True

    def _scroll_text_chat(self, amount: int) -> None:
        if not self.text_chat:
            return
        self.text_chat["scroll"] = max(0, int(self.text_chat.get("scroll", 0)) + amount)

    def _interact(self) -> bool:
        front = self._front_position()
        front_agent = self._agent_at(front)
        if front_agent:
            self._open_direct_chat(front_agent)
            return False
        front_object = self._object_at(front)
        if front_object:
            options = self._object_interaction_options(front_object)
            if len(options) > 1:
                self.object_menu = {"object_id": front_object.id, "options": options}
                return False
            interaction_id = str(options[0]["id"]) if options else ""
            interact_with_object(self.world, front_object, interaction_id)
            return True
        self.world.log("player_interact_none", "There is nobody and nothing directly in front of you.", tags=["interact"])
        return False

    def _object_interaction_options(self, obj) -> list[dict[str, str]]:
        options: list[dict[str, str]] = []
        for interaction_id in obj.interactions:
            spec = interaction_spec(obj, interaction_id)
            options.append(
                {
                    "id": interaction_id,
                    "label": str(spec.get("label") or interaction_id.replace("_", " ").title()),
                    "description": str(spec.get("description") or spec.get("message") or ""),
                }
            )
        return options

    def _talk(self) -> bool:
        front_agent = self._agent_at(self._front_position())
        if front_agent:
            self._open_direct_chat(front_agent)
            return False
        self.world.log("player_talk_none", "Face an agent on the tile ahead before starting a direct conversation.", tags=["dialogue"])
        return False

    def _open_text_chat(self) -> None:
        agents = self.world.nearby_agents(distance=1)
        if not agents:
            self.world.log("player_talk_none", "Nobody is on a neighbouring tile.", tags=["dialogue"])
            return
        target_ids = [agent.id for agent in agents]
        self.world.selected_agent_id = target_ids[0]
        self.text_chat = {
            "mode": "group",
            "title": "Group Chat",
            "target_ids": target_ids,
            "text": "",
            "scroll": 0,
            "effects": [],
        }

    def _open_direct_chat(self, agent) -> None:
        self.world.selected_agent_id = agent.id
        self.text_chat = {
            "mode": "direct",
            "title": f"Talk to {agent.name}",
            "target_ids": [agent.id],
            "text": "",
            "scroll": 0,
            "effects": [],
        }

    def _open_agent_dossier(self) -> None:
        agent = self._agent_at(self._front_position())
        if not agent and self.world.selected_agent_id:
            agent = self.world.agents.get(self.world.selected_agent_id)
        if not agent:
            nearby = self.world.nearby_agents(distance=2)
            agent = nearby[0] if nearby else next(iter(self.world.agents.values()), None)
        if not agent:
            return
        self.world.selected_agent_id = agent.id
        self.agent_dossier = {"agent_id": agent.id, "scroll": 0}

    def _send_group_chat(self, text: str, target_ids: list[str]) -> None:
        agents = [self.world.agents[agent_id] for agent_id in target_ids if agent_id in self.world.agents]
        if not agents:
            self.world.log("player_talk_none", "Nobody is close enough to answer.", tags=["dialogue"])
            return
        participant_names = [agent.name for agent in agents]
        is_direct = len(agents) == 1
        event_type = "player_direct_chat" if is_direct else "player_group_chat"
        chat_tag = "direct_chat" if is_direct else "group_chat"
        audience = participant_names[0] if is_direct else ", ".join(participant_names)
        self.world.chat("player", "You", text, source="player", audience_ids=target_ids)
        self.world.log(
            event_type,
            f"You say to {audience}: {text}",
            source="player",
            salience=7,
            tags=["dialogue", "player", chat_tag],
            metadata={"target_agent_ids": target_ids},
        )
        for agent in agents:
            before_social = snapshot_player_relationship(agent)
            parsed = self.brain.interpret_speech(self.world, agent, text)
            record_player_claims(self.world, agent, parsed)
            decision = decide_agent_response(self.world, agent, parsed)
            if decision.handled:
                voice = getattr(self.brain, "voice_agent_decision", None)
                if voice:
                    voiced = str(voice(self.world, agent, parsed, decision) or "").strip()
                    if voiced:
                        decision.reply = voiced
                apply_agent_decision(self.world, agent, parsed, decision)
                reply = decision.reply
            else:
                apply_open_dialogue_reaction(self.world, agent, parsed)
                reply = self.brain.chat(self.world, agent, text, participant_names)
            reaction = finalise_dialogue_reaction(self.world, agent, before_social, parsed, decision if decision.handled else None)
            self._append_chat_effect(reaction.summary)
            clean = reply.strip()
            if clean.lower().startswith(f"{agent.name.lower()}:"):
                clean = clean.split(":", 1)[1].strip()
            validation = validate_agent_dialogue(self.world, agent, clean)
            if validation.changed:
                agent.brain_risk = "Grounded dialogue rewrite: " + "; ".join(validation.rejected_physical_claims[:2])
            clean = validation.text
            agent.last_dialogue = f"{agent.name}: {clean}"
            agent.last_player_contact_turn = self.world.turn
            if decision.action != "hostile_alarm" and not agent.following_player and not agent.command_target_object_id:
                agent.command_hold_turns = max(agent.command_hold_turns, 3)
                agent.command_reason = "staying after player conversation"
            self.world.chat(agent.id, agent.name, clean, source="agent", audience_ids=target_ids)
            if not decision.handled:
                self.world.log(
                    "agent_chat_response",
                    f"{agent.name}: {clean}",
                    source=agent.id,
                    salience=7,
                    tags=["dialogue", "agent", chat_tag],
                    metadata={"agent_id": agent.id, "participants": participant_names},
                )

    def _append_chat_effect(self, summary: str) -> None:
        if not self.text_chat:
            return
        effects = list(self.text_chat.get("effects") or [])
        effects.append(summary)
        self.text_chat["effects"] = effects[-4:]

    def _give_item_to_front_agent(self) -> None:
        agent = self._agent_at(self._front_position())
        if not agent:
            self.world.log("item_give_none", "Face an agent before giving an item.", tags=["item", "inventory"])
            return
        item_id = first_transferable_item(self.world.player.inventory)
        if not item_id:
            self.world.log("item_give_empty", "Your inventory is empty.", tags=["item", "inventory"])
            return
        if transfer_item(self.world, "player", agent.id, item_id, "player quick give"):
            agent.social_to_player.trust += 1.5
            agent.social_to_player.affinity += 1.0
            agent.social_to_player.clamp()
            self.world.selected_agent_id = agent.id
            self.world.chat(agent.id, agent.name, f"I have {item_name(item_id)}. I will remember that.", source="agent", audience_ids=[agent.id])
            if item_id == "medkit" and "wounded" in agent.status_flags:
                apply_agent_intent(self.world, agent.id, "use_inventory_item", {"item_id": "medkit"}, rationale="player gave medical supplies")

    def _request_item_from_front_agent(self) -> None:
        agent = self._agent_at(self._front_position())
        if not agent:
            self.world.log("item_request_none", "Face an agent before requesting an item.", tags=["item", "inventory"])
            return
        item_id = first_transferable_item(agent.inventory)
        if not item_id:
            self.world.log("item_request_empty", f"{agent.name} has nothing to give.", tags=["item", "inventory"])
            return
        if agent.social_to_player.trust < 35 and item_id not in {"medkit", "ration"}:
            agent.social_to_player.resentment += 2.0
            agent.social_to_player.clamp()
            self.world.chat(agent.id, agent.name, f"No. I am not handing over {item_name(item_id)} right now.", source="agent", audience_ids=[agent.id])
            self.world.log("item_request_refused", f"{agent.name} refuses to give you {item_name(item_id)}.", source=agent.id, tags=["item", "inventory", "social"])
            return
        if transfer_item(self.world, agent.id, "player", item_id, "player quick request"):
            self.world.selected_agent_id = agent.id
            self.world.chat(agent.id, agent.name, f"Take {item_name(item_id)}. Use it carefully.", source="agent", audience_ids=[agent.id])

    def _open_model_settings(self) -> None:
        self.model_settings = load_game_model_settings(self.base_dir)
        self.model_settings_ui = {
            "selected": 0,
            "editing": False,
            "draft": dict(self.model_settings.role_models),
            "available": list(self.model_settings.available_models),
            "status": "Choose role, Enter edit, Tab cycle, A all, P powerful, H helper, Ctrl+S save.",
        }

    def _handle_model_settings_text(self, text: str) -> None:
        if not self.model_settings_ui:
            return
        role = MODEL_ROLES[int(self.model_settings_ui.get("selected", 0)) % len(MODEL_ROLES)]
        draft = dict(self.model_settings_ui.get("draft") or {})
        draft[role] = str(draft.get(role, "")) + text
        self.model_settings_ui["draft"] = draft

    def _handle_model_settings_key(self, key: int) -> bool:
        pg = self.pygame
        if not self.model_settings_ui:
            return True
        selected = int(self.model_settings_ui.get("selected", 0))
        editing = bool(self.model_settings_ui.get("editing"))
        draft = dict(self.model_settings_ui.get("draft") or {})
        role = MODEL_ROLES[selected % len(MODEL_ROLES)]
        if key == pg.K_ESCAPE:
            if editing:
                self.model_settings_ui["editing"] = False
            else:
                self.model_settings_ui = None
            return True
        if editing:
            if key == pg.K_BACKSPACE:
                draft[role] = str(draft.get(role, ""))[:-1]
                self.model_settings_ui["draft"] = draft
                return True
            if key == pg.K_RETURN:
                self.model_settings_ui["editing"] = False
                return True
            return True
        if key in {pg.K_UP, pg.K_w}:
            self.model_settings_ui["selected"] = (selected - 1) % len(MODEL_ROLES)
            return True
        if key in {pg.K_DOWN, pg.K_s}:
            if key == pg.K_s and self.pygame.key.get_mods() & pg.KMOD_CTRL:
                self._save_model_settings_ui()
            else:
                self.model_settings_ui["selected"] = (selected + 1) % len(MODEL_ROLES)
            return True
        if key == pg.K_RETURN:
            self.model_settings_ui["editing"] = True
            return True
        if key == pg.K_TAB:
            available = list(self.model_settings_ui.get("available") or [])
            if available:
                current = str(draft.get(role, ""))
                index = available.index(current) if current in available else -1
                draft[role] = available[(index + 1) % len(available)]
                self.model_settings_ui["draft"] = draft
            return True
        if key in {pg.K_a, pg.K_p, pg.K_h}:
            group = "all" if key == pg.K_a else "powerful" if key == pg.K_p else "helper"
            model = self._selected_model_for_preset(draft, role)
            if not model:
                self.model_settings_ui["status"] = "Pick or type a model first, then apply it to a group."
                return True
            self.model_settings_ui["draft"] = apply_model_preset(draft, model, group)
            label = "all roles" if group == "all" else "chat/scene/reasoning" if group == "powerful" else "semantic/fast/summarizer/maintenance"
            self.model_settings_ui["status"] = f"Applied {model} to {label}. Ctrl+S saves."
            return True
        if key == pg.K_DELETE:
            draft.pop(role, None)
            self.model_settings_ui["draft"] = draft
            return True
        if key == pg.K_r:
            models = discover_ollama_models()
            available = list(self.model_settings_ui.get("available") or [])
            merge_discovered_models(self.model_settings, [*available, *models])
            self.model_settings_ui["available"] = list(self.model_settings.available_models)
            self.model_settings_ui["status"] = f"Refreshed models: {len(models)} found." if models else "No local Ollama models discovered."
            return True
        if key == pg.K_s:
            self._save_model_settings_ui()
            return True
        if key == pg.K_m:
            self.model_settings_ui = None
            return True
        return True

    def _selected_model_for_preset(self, draft: dict[str, str], role: str) -> str:
        current = str(draft.get(role, "")).strip()
        if current:
            return current
        available = list(self.model_settings_ui.get("available") or []) if self.model_settings_ui else []
        return str(available[0]).strip() if available else ""

    def _save_model_settings_ui(self) -> None:
        if not self.model_settings_ui:
            return
        draft = {
            role: str(model).strip()
            for role, model in dict(self.model_settings_ui.get("draft") or {}).items()
            if role in MODEL_ROLES and str(model).strip()
        }
        self.model_settings.role_models = draft
        self.model_settings.available_models = list(self.model_settings_ui.get("available") or [])
        for model in draft.values():
            merge_discovered_models(self.model_settings, [model])
        path = save_game_model_settings(self.base_dir, self.model_settings)
        if hasattr(self.brain, "reload_model_settings"):
            self.brain.reload_model_settings()
        self.model_settings_ui["available"] = list(self.model_settings.available_models)
        self.model_settings_ui["status"] = f"Saved model roles to {path.name}."
        self.world.log("model_settings_saved", "LLM model role settings saved for the sandbox.", tags=["settings", "llm"])

    def _open_dialogue_menu(self, agent) -> None:
        self.world.selected_agent_id = agent.id
        self.dialogue_menu = {
            "agent_id": agent.id,
            "options": build_dialogue_options(self.world, agent),
        }

    def _maybe_open_initiated_chat(self) -> None:
        if self.text_chat or self.dialogue_menu or self.agent_dossier or self.object_menu:
            return
        event = next((item for item in reversed(self.world.event_log[-6:]) if item.event_type == "agent_initiates_chat"), None)
        if not event or event.event_id == self.last_auto_chat_event_id:
            return
        agent_id = str(event.metadata.get("agent_id") or event.source or "")
        agent = self.world.agents.get(agent_id)
        if not agent or agent.position.manhattan(self.world.player.position) > 1:
            return
        self.last_auto_chat_event_id = event.event_id
        self._open_direct_chat(agent)
        if self.text_chat is not None:
            self.text_chat["initiated"] = True

    def _front_position(self):
        from mozok_game.engine.models import Position

        dx, dy = FACING_DELTAS[self.world.player_facing]
        return Position(self.world.player.position.x + dx, self.world.player.position.y + dy)

    def _agent_at(self, position):
        for agent in self.world.agents.values():
            if agent.alive and agent.position.x == position.x and agent.position.y == position.y:
                return agent
        return None

    def _object_at(self, position):
        for obj in self.world.objects.values():
            if obj.position.x == position.x and obj.position.y == position.y:
                return obj
        return None
