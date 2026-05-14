from __future__ import annotations

from pathlib import Path
from typing import Any

from mozok_game.engine.models import Agent, Position, WorldObject
from mozok_game.engine.world_state import WorldState

TILE_COLOURS: dict[str, tuple[int, int, int]] = {
    "sand": (191, 164, 101),
    "grass": (55, 119, 76),
    "forest": (26, 75, 48),
    "water": (40, 92, 138),
    "rock": (67, 68, 75),
    "camp": (143, 87, 48),
    "cave": (42, 38, 55),
    "ruins": (111, 112, 118),
}

TILE_NAMES: dict[str, str] = {
    "sand": "shore sand",
    "grass": "island grass",
    "forest": "dense palms",
    "water": "dark water",
    "rock": "black rock",
    "camp": "camp ground",
    "cave": "cave stone",
    "ruins": "old ruins",
}

EMOTION_COLOURS: dict[str, tuple[int, int, int]] = {
    "neutral": (190, 190, 190),
    "happy": (235, 210, 86),
    "afraid": (118, 140, 230),
    "angry": (214, 82, 70),
    "curious": (164, 105, 220),
    "tired": (125, 125, 145),
    "sad": (82, 122, 190),
    "suspicious": (72, 150, 110),
}

OBJECT_MARKERS = {
    "water_source": "SPRING",
    "food_crate": "CRATE",
    "campfire": "FIRE",
    "cave_entrance": "CAVE",
    "broken_radio": "RADIO",
    "shelter": "SHELTER",
}

FACING_DELTAS = {
    "north": (0, -1),
    "east": (1, 0),
    "south": (0, 1),
    "west": (-1, 0),
}

RIGHT_DELTAS = {
    "north": (1, 0),
    "east": (0, 1),
    "south": (-1, 0),
    "west": (0, -1),
}


class Renderer:
    def __init__(self, pygame: Any, screen: Any, base_dir: Path) -> None:
        self.pygame = pygame
        self.screen = screen
        self.base_dir = base_dir
        self.font = pygame.font.SysFont("consolas", 17)
        self.small = pygame.font.SysFont("consolas", 14)
        self.tiny = pygame.font.SysFont("consolas", 12)
        self.title = pygame.font.SysFont("consolas", 26, bold=True)
        self.label = pygame.font.SysFont("consolas", 18, bold=True)
        self.debug = False
        self.avatar_cache: dict[tuple[str, str], Any] = {}

    def draw(self, world: WorldState, dialogue_menu: dict | None = None) -> None:
        self.screen.fill((10, 12, 18))
        view_rect = self.pygame.Rect(16, 16, 760, 470)
        side_rect = self.pygame.Rect(796, 16, 368, 470)
        feed_rect = self.pygame.Rect(16, 504, 1148, 200)
        self._draw_first_person_view(world, view_rect)
        self._draw_side_panel(world, side_rect)
        self._draw_bottom_panel(world, feed_rect)
        if self.debug:
            self._draw_debug(world)
        if dialogue_menu:
            self._draw_dialogue_menu(world, dialogue_menu)
        self.pygame.display.flip()

    def _draw_first_person_view(self, world: WorldState, rect: Any) -> None:
        self._draw_scene_backdrop(world, rect)
        self._draw_floor_path(world, rect)
        self._draw_side_depth_markers(world, rect)
        self._draw_visible_objects(world, rect)
        self._draw_visible_agents(world, rect)
        self._draw_vignette(rect)
        self._draw_minimap(world, self.pygame.Rect(rect.x + 16, rect.y + 292, 206, 158))
        facing = world.player_facing.upper()
        self._line(rect.x + 18, rect.y + 18, f"MOZOK ISLAND / FACING {facing}", (244, 239, 222), self.label)
        front = self._relative_position(world.player.position, world.player_facing, 1, 0)
        front_name = self._tile_name(world, front)
        self._line(rect.x + 18, rect.y + 44, f"Ahead: {front_name}", (210, 220, 218), self.small)

    def _draw_scene_backdrop(self, world: WorldState, rect: Any) -> None:
        front = self._relative_position(world.player.position, world.player_facing, 1, 0)
        colour = self._tile_colour_at(world, front)
        sky = self._mix((21, 31, 48), colour, 0.18)
        horizon = self._mix((44, 58, 66), colour, 0.22)
        ground = self._mix((34, 36, 35), colour, 0.35)
        self.pygame.draw.rect(self.screen, sky, rect, border_radius=8)
        self.pygame.draw.rect(self.screen, horizon, self.pygame.Rect(rect.x, rect.y + 142, rect.w, 108))
        self.pygame.draw.rect(self.screen, ground, self.pygame.Rect(rect.x, rect.y + 250, rect.w, rect.h - 250), border_radius=8)
        for i in range(0, 6):
            y = rect.y + 250 + i * 34
            shade = self._mix(ground, (5, 7, 9), i * 0.07)
            self.pygame.draw.rect(self.screen, shade, self.pygame.Rect(rect.x, y, rect.w, 34))
        self.pygame.draw.line(self.screen, (136, 145, 145), (rect.x + 26, rect.y + 250), (rect.right - 26, rect.y + 250), 1)
        self.pygame.draw.rect(self.screen, (71, 78, 91), rect, width=1, border_radius=8)

    def _draw_floor_path(self, world: WorldState, rect: Any) -> None:
        center_x = rect.centerx
        layers = {
            4: (rect.y + 246, 132, 44),
            3: (rect.y + 290, 220, 56),
            2: (rect.y + 346, 350, 68),
            1: (rect.y + 414, 540, 70),
        }
        for depth in range(4, 0, -1):
            top_y, top_w, height = layers[depth]
            bottom_w = top_w + 94
            pos = self._relative_position(world.player.position, world.player_facing, depth, 0)
            walkable = world.grid.is_walkable(pos)
            colour = self._tile_colour_at(world, pos)
            points = [
                (center_x - top_w // 2, top_y),
                (center_x + top_w // 2, top_y),
                (center_x + bottom_w // 2, top_y + height),
                (center_x - bottom_w // 2, top_y + height),
            ]
            self.pygame.draw.polygon(self.screen, self._mix(colour, (18, 18, 22), 0.22), points)
            self.pygame.draw.polygon(self.screen, self._mix((235, 230, 205), colour, 0.72), points, width=1)
            if not walkable:
                wall = self.pygame.Rect(center_x - top_w // 2, top_y - 82, top_w, height + 92)
                self.pygame.draw.rect(self.screen, self._mix(colour, (10, 10, 12), 0.35), wall, border_radius=4)
                self.pygame.draw.rect(self.screen, (190, 184, 162), wall, width=1, border_radius=4)
                self._centered(wall, TILE_NAMES.get(world.grid.tile_at(pos).kind if world.grid.in_bounds(pos) else "rock", "blocked"), (232, 229, 210), self.small)

    def _draw_side_depth_markers(self, world: WorldState, rect: Any) -> None:
        center_x = rect.centerx
        for depth in range(4, 0, -1):
            scale = self._depth_scale(depth)
            y = int(rect.y + 246 + (4 - depth) * 57)
            side_w = int(92 * scale)
            side_h = int(78 * scale)
            offset = int(165 * scale + (4 - depth) * 54)
            for side in (-1, 1):
                pos = self._relative_position(world.player.position, world.player_facing, depth, side)
                colour = self._tile_colour_at(world, pos)
                panel = self.pygame.Rect(center_x + side * offset - side_w // 2, y - side_h // 2, side_w, side_h)
                if not world.grid.is_walkable(pos):
                    self.pygame.draw.rect(self.screen, self._mix(colour, (8, 9, 12), 0.28), panel, border_radius=5)
                    self.pygame.draw.rect(self.screen, (96, 101, 105), panel, width=1, border_radius=5)
                elif self._object_at(world, pos) or self._agent_at(world, pos):
                    self.pygame.draw.rect(self.screen, self._mix(colour, (232, 217, 165), 0.18), panel, border_radius=5)
                    self.pygame.draw.rect(self.screen, (204, 190, 133), panel, width=1, border_radius=5)

    def _draw_visible_objects(self, world: WorldState, rect: Any) -> None:
        for depth in range(4, 0, -1):
            for side in (-1, 0, 1):
                pos = self._relative_position(world.player.position, world.player_facing, depth, side)
                obj = self._object_at(world, pos)
                if obj:
                    self._draw_object_billboard(rect, obj, depth, side)

    def _draw_visible_agents(self, world: WorldState, rect: Any) -> None:
        for depth in range(4, 0, -1):
            for side in (-1, 0, 1):
                pos = self._relative_position(world.player.position, world.player_facing, depth, side)
                agent = self._agent_at(world, pos)
                if agent:
                    self._draw_agent_billboard(rect, agent, depth, side)

    def _draw_object_billboard(self, rect: Any, obj: WorldObject, depth: int, side: int) -> None:
        box = self._billboard_rect(rect, depth, side, agent=False)
        colour = {
            "water_source": (72, 159, 212),
            "food_crate": (168, 112, 56),
            "campfire": (232, 118, 54),
            "cave_entrance": (84, 78, 104),
            "broken_radio": (120, 134, 145),
            "shelter": (115, 139, 84),
        }.get(obj.kind, (190, 190, 170))
        self.pygame.draw.rect(self.screen, (14, 16, 20), box.move(5, 7), border_radius=8)
        self.pygame.draw.rect(self.screen, colour, box, border_radius=8)
        self.pygame.draw.rect(self.screen, self._mix((255, 255, 240), colour, 0.65), box, width=2, border_radius=8)
        marker = OBJECT_MARKERS.get(obj.kind, obj.name.upper()[:8])
        self._centered(box, marker, (18, 18, 20), self.small if depth > 1 else self.label)
        name_rect = self.pygame.Rect(box.x - 18, box.bottom + 6, box.w + 36, 24)
        self._centered(name_rect, obj.name[:24], (238, 234, 211), self.small)

    def _draw_agent_billboard(self, rect: Any, agent: Agent, depth: int, side: int) -> None:
        box = self._billboard_rect(rect, depth, side, agent=True)
        self.pygame.draw.rect(self.screen, (8, 9, 12), box.move(6, 8), border_radius=8)
        avatar = self._load_avatar(agent)
        if avatar:
            image = self.pygame.transform.smoothscale(avatar, (box.w, box.h))
            self.screen.blit(image, box)
            self.pygame.draw.rect(self.screen, EMOTION_COLOURS.get(agent.emotion, (210, 210, 210)), box, width=3, border_radius=8)
        else:
            colour = EMOTION_COLOURS.get(agent.emotion, (210, 210, 210))
            self.pygame.draw.rect(self.screen, colour, box, border_radius=8)
            self._centered(box, agent.name[0].upper(), (15, 15, 15), self.title)
        label = self.pygame.Rect(box.x - 28, box.bottom + 6, box.w + 56, 40)
        self.pygame.draw.rect(self.screen, (16, 18, 24), label, border_radius=6)
        self.pygame.draw.rect(self.screen, (82, 87, 100), label, width=1, border_radius=6)
        self._centered(self.pygame.Rect(label.x, label.y + 2, label.w, 18), agent.name, (246, 242, 226), self.small)
        self._centered(self.pygame.Rect(label.x, label.y + 20, label.w, 16), agent.emotion, EMOTION_COLOURS.get(agent.emotion, (210, 210, 210)), self.tiny)

    def _draw_minimap(self, world: WorldState, rect: Any) -> None:
        self.pygame.draw.rect(self.screen, (13, 15, 20), rect, border_radius=8)
        self.pygame.draw.rect(self.screen, (72, 78, 92), rect, width=1, border_radius=8)
        tile = min((rect.w - 18) // world.grid.width, (rect.h - 30) // world.grid.height)
        ox = rect.x + 9
        oy = rect.y + 22
        self._line(rect.x + 10, rect.y + 7, "TACTICAL MAP", (225, 216, 172), self.tiny)
        for y in range(world.grid.height):
            for x in range(world.grid.width):
                map_rect = self.pygame.Rect(ox + x * tile, oy + y * tile, tile - 1, tile - 1)
                kind = world.grid.tiles[y][x].kind
                self.pygame.draw.rect(self.screen, TILE_COLOURS.get(kind, (80, 80, 80)), map_rect)
        for obj in world.objects.values():
            self._draw_minimap_dot(ox, oy, tile, obj.position, (238, 212, 110))
        for agent in world.agents.values():
            self._draw_minimap_dot(ox, oy, tile, agent.position, EMOTION_COLOURS.get(agent.emotion, (220, 220, 220)))
        p = world.player.position
        px = ox + p.x * tile + tile // 2
        py = oy + p.y * tile + tile // 2
        dx, dy = FACING_DELTAS[world.player_facing]
        arrow = [(px + dx * 6, py + dy * 6), (px - dy * 4, py + dx * 4), (px + dy * 4, py - dx * 4)]
        self.pygame.draw.polygon(self.screen, (250, 250, 248), arrow)

    def _draw_side_panel(self, world: WorldState, rect: Any) -> None:
        self.pygame.draw.rect(self.screen, (20, 23, 30), rect, border_radius=8)
        self.pygame.draw.rect(self.screen, (68, 75, 88), rect, width=1, border_radius=8)
        self.screen.blit(self.title.render("MOZOK Island", True, (244, 242, 235)), (rect.x + 16, rect.y + 14))
        self._line(rect.x + 18, rect.y + 48, f"Turn {world.turn}", (194, 203, 209), self.small)
        y = rect.y + 76
        for agent in world.agents.values():
            self._draw_agent_card(agent, rect.x + 12, y, rect.w - 24, 118)
            y += 126

    def _draw_agent_card(self, agent: Agent, x: int, y: int, w: int, h: int) -> None:
        card = self.pygame.Rect(x, y, w, h)
        self.pygame.draw.rect(self.screen, (29, 33, 43), card, border_radius=8)
        self.pygame.draw.rect(self.screen, (66, 74, 91), card, width=1, border_radius=8)
        avatar_rect = self.pygame.Rect(x + 10, y + 10, 68, 68)
        avatar = self._load_avatar(agent)
        if avatar:
            image = self.pygame.transform.smoothscale(avatar, (avatar_rect.w, avatar_rect.h))
            self.screen.blit(image, avatar_rect)
        else:
            self.pygame.draw.rect(self.screen, EMOTION_COLOURS.get(agent.emotion, (180, 180, 180)), avatar_rect, border_radius=8)
            self._centered(avatar_rect, agent.name[0].upper(), (20, 20, 20), self.title)
        self.pygame.draw.rect(self.screen, EMOTION_COLOURS.get(agent.emotion, (210, 210, 210)), avatar_rect, width=2, border_radius=8)
        self._line(x + 90, y + 8, f"{agent.name} / {agent.emotion}", (246, 244, 232), self.small)
        self._line(x + 90, y + 27, f"Goal: {agent.current_goal[:27]}", (194, 204, 204), self.tiny)
        self._draw_bar(x + 90, y + 49, 104, "Hunger", agent.needs.hunger, (205, 124, 82))
        self._draw_bar(x + 214, y + 49, 104, "Thirst", agent.needs.thirst, (78, 150, 210))
        self._draw_bar(x + 90, y + 74, 104, "Stress", agent.needs.stress, (184, 91, 112))
        self._draw_bar(x + 214, y + 74, 104, "Trust", agent.social_to_player.trust, (98, 181, 133))
        rationale = agent.last_rationale or "watching the camp"
        self._line(x + 10, y + 94, f"Intent: {agent.last_action[:18]} - {rationale[:48]}", (218, 216, 194), self.tiny)

    def _draw_bottom_panel(self, world: WorldState, rect: Any) -> None:
        self.pygame.draw.rect(self.screen, (22, 25, 32), rect, border_radius=8)
        self.pygame.draw.rect(self.screen, (68, 74, 88), rect, width=1, border_radius=8)
        left_x = rect.x + 16
        mid_x = rect.x + 476
        right_x = rect.x + 824
        self._line(left_x, rect.y + 12, "WORLD EVENT FEED", (232, 216, 155), self.small)
        yy = rect.y + 38
        for event in world.event_log[-6:]:
            text = f"[{event.turn:03d}] {event.content}"
            self._line(left_x, yy, text[:62], (220, 221, 215), self.small)
            yy += 24

        agent = self._focused_agent(world)
        self._line(mid_x, rect.y + 12, "COGNITIVE FIELD", (232, 216, 155), self.small)
        if agent:
            score = f"{agent.brain_focus_score:.2f}" if agent.brain_focus_score else "local"
            self._line(mid_x, rect.y + 38, f"{agent.name} focus / score {score}", (218, 226, 226), self.small)
            lines = self._wrap(agent.brain_broadcast or agent.brain_focus, 45, 4)
            yy = rect.y + 66
            for line in lines:
                self._line(mid_x, yy, line, (238, 235, 222), self.small)
                yy += 21
            memory = agent.brain_memory or "No strong memory resonance."
            self._line(mid_x, rect.y + 154, f"Risk: {agent.brain_risk}", (210, 204, 190), self.tiny)
            self._line(mid_x, rect.y + 171, f"Memory: {memory[:40]}", (202, 212, 218), self.tiny)
        else:
            self._line(mid_x, rect.y + 38, "No agent focus selected yet.", (218, 226, 226), self.small)

        self._line(right_x, rect.y + 12, "MEMORY FLASHES / SOCIAL", (232, 216, 155), self.small)
        flash_y = rect.y + 38
        for flash in world.brain_flashes[-4:]:
            name = world.agents.get(flash.agent_id).name if world.agents.get(flash.agent_id) else flash.agent_id
            self._line(right_x, flash_y, f"{name}: {flash.title}", (235, 229, 206), self.tiny)
            flash_y += 16
            for line in self._wrap(flash.content, 42, 2):
                self._line(right_x, flash_y, line, (205, 210, 212), self.tiny)
                flash_y += 15
            flash_y += 4

        nearby = world.nearby_agents(distance=2)
        social_y = rect.y + 150
        if nearby:
            nearby_agent = nearby[0]
            self._line(right_x, social_y, f"Near: {nearby_agent.name} trust {nearby_agent.social_to_player.trust:.0f} fear {nearby_agent.social_to_player.fear:.0f}", (218, 226, 226), self.tiny)
            social_line = nearby_agent.last_dialogue or f"{nearby_agent.name} is close enough to talk."
        else:
            self._line(right_x, social_y, "No one is close.", (218, 226, 226), self.tiny)
            social_line = world.last_message
        self._line(right_x, social_y + 17, social_line[:42], (238, 235, 222), self.tiny)
        front = self._relative_position(world.player.position, world.player_facing, 1, 0)
        front_obj = self._object_at(world, front)
        front_agent = self._agent_at(world, front)
        target = front_agent.name if front_agent else front_obj.name if front_obj else self._tile_name(world, front)
        self._line(left_x, rect.y + 172, f"Camera focus: {target}", (202, 212, 218), self.small)

    def _draw_dialogue_menu(self, world: WorldState, dialogue_menu: dict) -> None:
        agent = world.agents.get(dialogue_menu["agent_id"])
        if not agent:
            return
        overlay = self.pygame.Surface(self.screen.get_size(), self.pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 150))
        self.screen.blit(overlay, (0, 0))
        rect = self.pygame.Rect(260, 118, 660, 372)
        self.pygame.draw.rect(self.screen, (22, 25, 33), rect, border_radius=8)
        self.pygame.draw.rect(self.screen, (115, 124, 145), rect, width=1, border_radius=8)
        avatar_rect = self.pygame.Rect(rect.x + 22, rect.y + 24, 132, 132)
        avatar = self._load_avatar(agent)
        if avatar:
            image = self.pygame.transform.smoothscale(avatar, (avatar_rect.w, avatar_rect.h))
            self.screen.blit(image, avatar_rect)
        else:
            self.pygame.draw.rect(self.screen, EMOTION_COLOURS.get(agent.emotion, (190, 190, 190)), avatar_rect, border_radius=8)
        self.pygame.draw.rect(self.screen, EMOTION_COLOURS.get(agent.emotion, (210, 210, 210)), avatar_rect, width=3, border_radius=8)
        self._line(rect.x + 178, rect.y + 26, f"Talk to {agent.name}", (248, 244, 232), self.title)
        self._line(rect.x + 180, rect.y + 62, f"{agent.role} / {agent.emotion}", (209, 217, 219), self.small)
        self._line(rect.x + 180, rect.y + 88, f"Focus: {agent.brain_focus[:54]}", (232, 226, 201), self.small)
        self._line(rect.x + 180, rect.y + 112, f"Memory: {(agent.brain_memory or 'none')[:53]}", (203, 213, 218), self.small)
        y = rect.y + 178
        for index, option in enumerate(dialogue_menu.get("options", []), start=1):
            option_rect = self.pygame.Rect(rect.x + 24, y, rect.w - 48, 48)
            self.pygame.draw.rect(self.screen, (34, 38, 49), option_rect, border_radius=7)
            self.pygame.draw.rect(self.screen, (78, 87, 105), option_rect, width=1, border_radius=7)
            self._line(option_rect.x + 16, option_rect.y + 14, f"{index}. {option['label']}", (239, 239, 226), self.label)
            y += 60
        self._line(rect.x + 24, rect.bottom - 28, "1-3 choose / T or Esc close", (178, 186, 193), self.small)

    def _focused_agent(self, world: WorldState) -> Agent | None:
        if world.selected_agent_id and world.selected_agent_id in world.agents:
            return world.agents[world.selected_agent_id]
        nearby = world.nearby_agents(distance=2)
        if nearby:
            return nearby[0]
        if world.brain_flashes:
            return world.agents.get(world.brain_flashes[-1].agent_id)
        if world.agents:
            return next(iter(world.agents.values()))
        return None

    def _draw_debug(self, world: WorldState) -> None:
        rect = self.pygame.Rect(24, 24, 520, 232)
        self.pygame.draw.rect(self.screen, (0, 0, 0), rect, border_radius=8)
        self.pygame.draw.rect(self.screen, (180, 180, 180), rect, width=1, border_radius=8)
        y = rect.y + 14
        self._line(rect.x + 14, y, "DEBUG: world state / MOZOK-facing signals", (255, 245, 180), self.small)
        y += 24
        self._line(rect.x + 14, y, f"Player pos: {world.player.position.x},{world.player.position.y} facing={world.player_facing} inv={world.player.inventory}", (230, 230, 230), self.small)
        y += 22
        for agent in world.agents.values():
            text = (
                f"{agent.id}: pos={agent.position.x},{agent.position.y} emotion={agent.emotion} "
                f"h={agent.needs.hunger:.0f} t={agent.needs.thirst:.0f} s={agent.needs.stress:.0f} action={agent.last_action}"
            )
            self._line(rect.x + 14, y, text[:78], (210, 210, 210), self.tiny)
            y += 20

    def _draw_bar(self, x: int, y: int, w: int, label: str, value: float, colour: tuple[int, int, int]) -> None:
        self._line(x, y - 11, f"{label} {value:.0f}", (190, 197, 202), self.tiny)
        bg = self.pygame.Rect(x, y + 4, w, 7)
        self.pygame.draw.rect(self.screen, (15, 17, 22), bg, border_radius=3)
        fill = self.pygame.Rect(x, y + 4, int(w * max(0.0, min(100.0, value)) / 100.0), 7)
        self.pygame.draw.rect(self.screen, colour, fill, border_radius=3)

    def _draw_minimap_dot(self, ox: int, oy: int, tile: int, pos: Position, colour: tuple[int, int, int]) -> None:
        cx = ox + pos.x * tile + tile // 2
        cy = oy + pos.y * tile + tile // 2
        self.pygame.draw.circle(self.screen, colour, (cx, cy), max(2, tile // 2))

    def _draw_vignette(self, rect: Any) -> None:
        self.pygame.draw.rect(self.screen, (6, 8, 12), self.pygame.Rect(rect.x, rect.y, rect.w, 8), border_radius=8)
        self.pygame.draw.rect(self.screen, (6, 8, 12), self.pygame.Rect(rect.x, rect.bottom - 8, rect.w, 8), border_radius=8)
        self.pygame.draw.rect(self.screen, (6, 8, 12), self.pygame.Rect(rect.x, rect.y, 8, rect.h), border_radius=8)
        self.pygame.draw.rect(self.screen, (6, 8, 12), self.pygame.Rect(rect.right - 8, rect.y, 8, rect.h), border_radius=8)

    def _billboard_rect(self, rect: Any, depth: int, side: int, agent: bool) -> Any:
        scale = self._depth_scale(depth)
        w = int((128 if agent else 116) * scale)
        h = int((176 if agent else 92) * scale)
        center_x = rect.centerx + side * int(250 * scale + (4 - depth) * 34)
        bottom = rect.y + 426 - int((depth - 1) * 54)
        return self.pygame.Rect(center_x - w // 2, bottom - h, w, h)

    def _depth_scale(self, depth: int) -> float:
        return {1: 1.0, 2: 0.72, 3: 0.52, 4: 0.38}[depth]

    def _relative_position(self, origin: Position, facing: str, depth: int, side: int) -> Position:
        fx, fy = FACING_DELTAS[facing]
        rx, ry = RIGHT_DELTAS[facing]
        return Position(origin.x + fx * depth + rx * side, origin.y + fy * depth + ry * side)

    def _tile_colour_at(self, world: WorldState, pos: Position) -> tuple[int, int, int]:
        if not world.grid.in_bounds(pos):
            return TILE_COLOURS["rock"]
        return TILE_COLOURS.get(world.grid.tile_at(pos).kind, (80, 80, 80))

    def _tile_name(self, world: WorldState, pos: Position) -> str:
        if not world.grid.in_bounds(pos):
            return "edge of the island"
        return TILE_NAMES.get(world.grid.tile_at(pos).kind, "unknown ground")

    def _object_at(self, world: WorldState, pos: Position) -> WorldObject | None:
        for obj in world.objects.values():
            if obj.position.x == pos.x and obj.position.y == pos.y:
                return obj
        return None

    def _agent_at(self, world: WorldState, pos: Position) -> Agent | None:
        for agent in world.agents.values():
            if agent.alive and agent.position.x == pos.x and agent.position.y == pos.y:
                return agent
        return None

    def _load_avatar(self, agent: Agent) -> Any | None:
        key = (agent.avatar_folder, agent.emotion)
        if key in self.avatar_cache:
            return self.avatar_cache[key]
        path = self.base_dir / "data" / "avatars" / agent.avatar_folder / f"{agent.emotion}.png"
        if not path.exists():
            path = self.base_dir / "data" / "avatars" / agent.avatar_folder / "neutral.png"
        if not path.exists():
            self.avatar_cache[key] = None
            return None
        image = self.pygame.image.load(str(path)).convert_alpha()
        self.avatar_cache[key] = image
        return image

    def _centered(self, rect: Any, text: str, colour: tuple[int, int, int], font: Any) -> None:
        surf = font.render(text, True, colour)
        self.screen.blit(surf, (rect.centerx - surf.get_width() // 2, rect.centery - surf.get_height() // 2))

    def _line(self, x: int, y: int, text: str, colour: tuple[int, int, int], font: Any | None = None) -> None:
        self.screen.blit((font or self.font).render(text, True, colour), (x, y))

    def _mix(self, a: tuple[int, int, int], b: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
        t = max(0.0, min(1.0, amount))
        return tuple(int(a[i] * (1.0 - t) + b[i] * t) for i in range(3))

    def _wrap(self, text: str, width: int, limit: int) -> list[str]:
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if len(candidate) > width and current:
                lines.append(current)
                current = word
            else:
                current = candidate
            if len(lines) >= limit:
                break
        if current and len(lines) < limit:
            lines.append(current)
        return lines or [""]
