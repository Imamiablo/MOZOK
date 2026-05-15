from __future__ import annotations

from pathlib import Path

from mozok_game.engine.director import apply_dialogue_choice, build_dialogue_options
from mozok_game.engine.interactions import interact_with_object
from mozok_game.engine.tick_scheduler import run_agent_ticks
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
        self.world: WorldState = load_world(base_dir)
        self.brain = build_brain_client()
        self.dialogue_menu: dict | None = None
        self.text_chat: dict | None = None
        self.world.log("brain_mode", getattr(self.brain, "last_status", "Brain client ready"), source="game", salience=4, tags=["debug", "brain"])
        width = 1180
        height = 720
        self.screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption("MOZOK: Island Sandbox - First Person Prototype")
        self.clock = pygame.time.Clock()
        self.renderer = Renderer(pygame, self.screen, base_dir)

    def run(self) -> None:
        running = True
        while running:
            for event in self.pygame.event.get():
                if event.type == self.pygame.QUIT:
                    running = False
                elif event.type == self.pygame.TEXTINPUT and self.text_chat:
                    self.text_chat["text"] += event.text
                elif event.type == self.pygame.KEYDOWN:
                    running = self._handle_key(event.key)
            self.renderer.draw(self.world, self.dialogue_menu, self.text_chat)
            self.clock.tick(30)
        self.pygame.quit()

    def _handle_key(self, key: int) -> bool:
        pg = self.pygame
        if self.text_chat:
            return self._handle_text_chat_key(key)
        if self.dialogue_menu:
            return self._handle_dialogue_key(key)
        if key == pg.K_ESCAPE:
            return False
        if key == pg.K_TAB:
            self.renderer.debug = not self.renderer.debug
            return True
        if key in {pg.K_SPACE}:
            self.world.log("player_wait", "You wait and listen to the island breathe.", tags=["wait"])
            run_agent_ticks(self.world, self.brain)
            return True
        if key in {pg.K_e}:
            if self._interact():
                run_agent_ticks(self.world, self.brain)
            return True
        if key in {pg.K_t}:
            self._open_text_chat()
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
            return True
        if key in {pg.K_DOWN, pg.K_s}:
            self._move_relative(-1)
            run_agent_ticks(self.world, self.brain)
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

    def _handle_text_chat_key(self, key: int) -> bool:
        pg = self.pygame
        if key == pg.K_ESCAPE:
            self.text_chat = None
            return True
        if key == pg.K_BACKSPACE:
            self.text_chat["text"] = self.text_chat["text"][:-1]
            return True
        if key == pg.K_RETURN:
            text = self.text_chat.get("text", "").strip()
            targets = list(self.text_chat.get("target_ids", []))
            self.text_chat = None
            if text and targets:
                self._send_group_chat(text, targets)
                run_agent_ticks(self.world, self.brain)
            return True
        return True

    def _interact(self) -> bool:
        front = self._front_position()
        front_agent = self._agent_at(front)
        if front_agent:
            self._open_dialogue_menu(front_agent)
            return False
        front_object = self._object_at(front)
        if front_object:
            interact_with_object(self.world, front_object)
            return True
        agents = self.world.nearby_agents(distance=1)
        if agents:
            self._open_dialogue_menu(agents[0])
            return False
        objects = self.world.nearby_objects(distance=1)
        if objects:
            interact_with_object(self.world, objects[0])
            return True
        self.world.log("player_interact_none", "There is nothing close enough to interact with.", tags=["interact"])
        return False

    def _talk(self) -> bool:
        front_agent = self._agent_at(self._front_position())
        if front_agent:
            self._open_dialogue_menu(front_agent)
            return False
        agents = self.world.nearby_agents(distance=2)
        if agents:
            self._open_dialogue_menu(agents[0])
            return False
        else:
            self.world.log("player_talk_none", "You call out, but nobody is close enough to answer.", tags=["dialogue"])
        return False

    def _open_text_chat(self) -> None:
        agents = self.world.nearby_agents(distance=1)
        if not agents:
            self.world.log("player_talk_none", "Nobody is on a neighbouring tile.", tags=["dialogue"])
            return
        target_ids = [agent.id for agent in agents]
        self.world.selected_agent_id = target_ids[0]
        self.text_chat = {
            "target_ids": target_ids,
            "text": "",
        }

    def _send_group_chat(self, text: str, target_ids: list[str]) -> None:
        agents = [self.world.agents[agent_id] for agent_id in target_ids if agent_id in self.world.agents]
        if not agents:
            self.world.log("player_talk_none", "Nobody is close enough to answer.", tags=["dialogue"])
            return
        participant_names = [agent.name for agent in agents]
        self.world.chat("player", "You", text, source="player")
        self.world.log(
            "player_group_chat",
            f"You say to {', '.join(participant_names)}: {text}",
            source="player",
            salience=7,
            tags=["dialogue", "player", "group_chat"],
            metadata={"target_agent_ids": target_ids},
        )
        for agent in agents:
            reply = self.brain.chat(self.world, agent, text, participant_names)
            clean = reply.strip()
            if clean.lower().startswith(f"{agent.name.lower()}:"):
                clean = clean.split(":", 1)[1].strip()
            agent.last_dialogue = f"{agent.name}: {clean}"
            self.world.chat(agent.id, agent.name, clean, source="agent")
            self.world.log(
                "agent_chat_response",
                f"{agent.name}: {clean}",
                source=agent.id,
                salience=7,
                tags=["dialogue", "agent", "group_chat"],
                metadata={"agent_id": agent.id, "participants": participant_names},
            )

    def _open_dialogue_menu(self, agent) -> None:
        self.world.selected_agent_id = agent.id
        self.dialogue_menu = {
            "agent_id": agent.id,
            "options": build_dialogue_options(self.world, agent),
        }

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
