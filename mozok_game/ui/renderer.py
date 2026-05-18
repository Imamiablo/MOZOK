from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from mozok_game.engine.inventory import inventory_label, item_capabilities, item_name
from mozok_game.engine.model_settings import MODEL_ROLES
from mozok_game.engine.models import Agent, Position, WorldObject
from mozok_game.engine.pressure import pressure_summary
from mozok_game.engine.relationships import social_state_for
from mozok_game.engine.world_state import WorldState
from mozok_game.ui.art_assets import ArtAssets

TILE_COLOURS: dict[str, tuple[int, int, int]] = {
    "floor": (75, 78, 72),
    "wall": (68, 68, 70),
    "void": (18, 18, 18),
    "water": (38, 83, 128),
}

TILE_NAMES: dict[str, str] = {
    "floor": "floor",
    "wall": "wall",
    "void": "edge",
    "water": "dark water",
}

EMOTION_COLOURS: dict[str, tuple[int, int, int]] = {
    "neutral": (194, 194, 184),
    "happy": (235, 210, 86),
    "afraid": (118, 140, 230),
    "angry": (214, 82, 70),
    "curious": (164, 105, 220),
    "tired": (125, 125, 145),
    "sad": (82, 122, 190),
    "suspicious": (72, 150, 110),
}

OBJECT_MARKERS: dict[str, str] = {}

OBJECT_COLOURS = {
    "food": (166, 105, 52),
    "water": (72, 159, 212),
    "fire": (232, 118, 54),
    "shelter": (115, 139, 84),
    "tool": (150, 154, 148),
    "medical": (196, 74, 72),
    "evidence": (209, 194, 140),
    "rest": (115, 139, 84),
    "danger": (128, 68, 72),
    "mystery": (84, 78, 104),
    "container": (118, 94, 62),
    "furniture": (124, 104, 78),
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

GOLD = (221, 176, 67)
GOLD_DARK = (117, 76, 25)
PAPER = (239, 227, 174)
INK = (41, 31, 24)
GREEN_PANEL = (49, 91, 70)
MAX_VIEW_DEPTH = 5
VIEW_SIDES = (-2, -1, 0, 1, 2)


class Renderer:
    def __init__(self, pygame: Any, screen: Any, base_dir: Path) -> None:
        self.pygame = pygame
        self.screen = screen
        self.base_dir = base_dir
        self.art = ArtAssets(pygame, base_dir)
        self.font = pygame.font.SysFont("georgia", 17)
        self.small = pygame.font.SysFont("georgia", 14)
        self.tiny = pygame.font.SysFont("georgia", 12)
        self.title = pygame.font.SysFont("georgia", 25, bold=True)
        self.label = pygame.font.SysFont("georgia", 18, bold=True)
        self.mono = pygame.font.SysFont("consolas", 13)
        self.debug = False
        self.bottom_tabs = ["conversation", "inventory", "relations", "agent", "memory"]
        self.bottom_tab = "conversation"
        self.avatar_cache: dict[tuple[str, str], Any] = {}

    def cycle_bottom_tab(self) -> None:
        index = self.bottom_tabs.index(self.bottom_tab) if self.bottom_tab in self.bottom_tabs else 0
        self.bottom_tab = self.bottom_tabs[(index + 1) % len(self.bottom_tabs)]

    def draw(
        self,
        world: WorldState,
        dialogue_menu: dict | None = None,
        text_chat: dict | None = None,
        agent_dossier: dict | None = None,
        object_menu: dict | None = None,
        model_settings_ui: dict | None = None,
    ) -> None:
        self._sync_art_pack(world)
        self.screen.fill((10, 9, 7))
        left_rect = self.pygame.Rect(8, 8, 150, 436)
        view_rect = self.pygame.Rect(168, 8, 944, 436)
        right_rect = self.pygame.Rect(1122, 8, 150, 436)
        bottom_rect = self.pygame.Rect(168, 452, 944, 260)

        self._draw_first_person_view(world, view_rect)
        self._draw_party_panels(world, left_rect, right_rect)
        self._draw_bottom_panel(world, bottom_rect)
        self._draw_corner_status(world)
        self._draw_player_inventory(world)

        if self.debug:
            self._draw_debug(world)
        if dialogue_menu:
            self._draw_dialogue_menu(world, dialogue_menu)
        if text_chat:
            self._draw_text_chat(world, text_chat)
        if agent_dossier:
            self._draw_agent_dossier(world, agent_dossier)
        if object_menu:
            self._draw_object_menu(world, object_menu)
        if model_settings_ui:
            self._draw_model_settings(world, model_settings_ui)
        self.pygame.display.flip()

    def _draw_first_person_view(self, world: WorldState, rect: Any) -> None:
        self._draw_scene_backdrop(world, rect)
        self._draw_corridor(world, rect)
        self._draw_visible_objects(world, rect)
        self._draw_visible_agents(world, rect)
        self._draw_view_shadow(rect)
        self._draw_minimap(world, self.pygame.Rect(rect.x + 18, rect.bottom - 142, 190, 122))
        self._draw_view_title(world, rect)

    def _draw_scene_backdrop(self, world: WorldState, rect: Any) -> None:
        current = world.player.position
        tile_kind = world.grid.tile_at(current).kind if world.grid.in_bounds(current) else "floor"
        ground = self._tile_colour(world, tile_kind)
        sky_top = self._mix((17, 30, 38), ground, 0.08)
        sky_low = self._mix((68, 84, 73), ground, 0.18)
        horizon = rect.y + 184

        for row in range(rect.h):
            t = row / max(1, rect.h - 1)
            if row < horizon - rect.y:
                colour = self._mix(sky_top, sky_low, t * 1.7)
            else:
                colour = self._mix(self._mix(ground, (34, 42, 30), 0.25), (0, 0, 0), (t - 0.42) * 0.42)
            self.pygame.draw.line(self.screen, colour, (rect.x, rect.y + row), (rect.right, rect.y + row))

        haze = self.pygame.Surface((rect.w, rect.h), self.pygame.SRCALPHA)
        tree_base = (18, 47, 34, 150)
        ridge = [
            (0, 174),
            (64, 158),
            (136, 170),
            (220, 146),
            (326, 170),
            (430, 152),
            (560, 166),
            (662, 143),
            (760, 171),
            (860, 152),
            (944, 168),
            (944, 230),
            (0, 230),
        ]
        self.pygame.draw.polygon(haze, tree_base, ridge)
        for i in range(18):
            x = int((i * 73 + 31) % rect.w)
            trunk_h = 34 + (i % 4) * 9
            self.pygame.draw.rect(haze, (35, 56, 37, 120), self.pygame.Rect(x, 152 - trunk_h // 4, 5, trunk_h))
            self.pygame.draw.circle(haze, (19, 62, 39, 125), (x + 2, 149 - trunk_h // 5), 18 + (i % 3) * 5)
        self.screen.blit(haze, rect)

    def _draw_corridor(self, world: WorldState, rect: Any) -> None:
        horizon_y = rect.y + 196
        self._draw_floor_grid(world, rect)
        self._draw_wall_grid(world, rect)
        self.pygame.draw.line(self.screen, (93, 110, 85), (rect.x + 28, horizon_y), (rect.right - 28, horizon_y), 1)

    def _draw_floor_grid(self, world: WorldState, rect: Any) -> None:
        for depth in range(MAX_VIEW_DEPTH, 0, -1):
            for side in VIEW_SIDES:
                pos = self._relative_position(world.player.position, world.player_facing, depth, side)
                if not self._cell_visible(world, depth, side) or self._sight_blocked(world, pos):
                    continue
                self._draw_floor_cell(world, rect, depth, side, pos)

    def _draw_wall_grid(self, world: WorldState, rect: Any) -> None:
        for depth in range(MAX_VIEW_DEPTH, 0, -1):
            for side in VIEW_SIDES:
                pos = self._relative_position(world.player.position, world.player_facing, depth, side)
                if not self._sight_blocked(world, pos):
                    continue
                tile_kind = world.grid.tile_at(pos).kind if world.grid.in_bounds(pos) else "wall"
                if self._side_wall_face_visible(world, depth, side):
                    self._draw_receding_wall_cell(world, rect, depth, side, tile_kind)
        for depth in range(MAX_VIEW_DEPTH, 0, -1):
            for side in VIEW_SIDES:
                pos = self._relative_position(world.player.position, world.player_facing, depth, side)
                if not self._sight_blocked(world, pos):
                    continue
                tile_kind = world.grid.tile_at(pos).kind if world.grid.in_bounds(pos) else "wall"
                if self._front_wall_face_visible(world, depth, side):
                    self._draw_front_wall_face(world, rect, depth, side, tile_kind)

    def _draw_floor_cell(self, world: WorldState, rect: Any, depth: int, side: int, pos: Position) -> None:
        points = self._cell_floor_poly(rect, depth, side)
        tile_kind = world.grid.tile_at(pos).kind if world.grid.in_bounds(pos) else "floor"
        base = self._tile_colour(world, tile_kind)
        shade = self._mix(base, (18, 21, 16), 0.12 + depth * 0.035)
        if side:
            shade = self._mix(shade, (0, 0, 0), min(0.16, abs(side) * 0.06))
        self.pygame.draw.polygon(self.screen, shade, points)

        is_water = self._tile_has_tag(world, tile_kind, "water")
        image = None if is_water else self._scene_image_for_kind(tile_kind, "floor", generic=True)
        if image:
            xs = [point[0] for point in points]
            ys = [point[1] for point in points]
            box = self.pygame.Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
            if box.w > 2 and box.h > 2:
                old_clip = self.screen.get_clip()
                self.screen.set_clip(rect.clip(box))
                texture = self.pygame.transform.smoothscale(image, (box.w, box.h))
                texture.set_alpha(54 if depth > 1 else 72)
                self.screen.blit(texture, box)
                self.screen.set_clip(old_clip)

        edge = self._mix((164, 145, 88), shade, 0.5)
        self.pygame.draw.polygon(self.screen, edge, points, width=1)
        if is_water:
            self._draw_water_surface(rect, points, depth, side)
        if side == 0:
            self.pygame.draw.line(self.screen, self._mix(edge, (0, 0, 0), 0.45), points[0], points[3], 1)
            self.pygame.draw.line(self.screen, self._mix(edge, (0, 0, 0), 0.45), points[1], points[2], 1)
        self._draw_walkable_feature(world, tile_kind, rect, depth, side)

    def _draw_wall_cell(self, world: WorldState, rect: Any, depth: int, side: int, pos: Position) -> None:
        tile_kind = world.grid.tile_at(pos).kind if world.grid.in_bounds(pos) else "wall"
        if side != 0:
            self._draw_receding_wall_cell(world, rect, depth, side, tile_kind)
            return

        wall = self._wall_rect(rect, depth, side)
        if wall.w <= 2 or wall.h <= 2:
            return

        base = self._tile_colour(world, tile_kind)
        is_water = self._tile_has_tag(world, tile_kind, "water")
        wall_img = None if is_water else self._scene_image_for_kind(tile_kind, "wall", generic=True)
        if wall_img:
            self._blit_scaled(wall_img, wall)
        else:
            top = self._mix(base, (21, 20, 18), 0.35)
            bottom = self._mix(base, (0, 0, 0), 0.22)
            for y in range(wall.h):
                colour = self._mix(top, bottom, y / max(1, wall.h - 1))
                self.pygame.draw.line(self.screen, colour, (wall.x, wall.y + y), (wall.right, wall.y + y))
        if is_water:
            for i in range(5):
                yy = wall.y + 18 + i * max(8, wall.h // 7)
                self.pygame.draw.arc(self.screen, (118, 174, 196), self.pygame.Rect(wall.x + 12, yy, wall.w - 24, 18), 0, math.pi, 1)

        veil = self.pygame.Surface((wall.w, wall.h), self.pygame.SRCALPHA)
        veil.fill((0, 0, 0, min(120, 24 + depth * 17 + abs(side) * 15)))
        self.screen.blit(veil, wall)
        self.pygame.draw.rect(self.screen, self._mix(GOLD_DARK, base, 0.32), wall, width=2)
        if side == 0 or depth <= 2:
            self._centered(self.pygame.Rect(wall.x, wall.y + 8, wall.w, 24), self._tile_name_for_kind(world, tile_kind, "blocked"), PAPER, self.tiny)

    def _draw_front_wall_face(self, world: WorldState, rect: Any, depth: int, side: int, tile_kind: str) -> None:
        points = self._cell_floor_poly(rect, depth, side)
        left_floor = points[3]
        right_floor = points[2]
        scale = self._depth_scale(depth)
        height = max(48, int(300 * scale))
        top_y = max(rect.y + 18, min(left_floor[1], right_floor[1]) - height)
        wall_poly = [(left_floor[0], top_y), (right_floor[0], top_y), right_floor, left_floor]
        xs = [point[0] for point in wall_poly]
        ys = [point[1] for point in wall_poly]
        box = rect.clip(self.pygame.Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)))
        if box.w <= 2 or box.h <= 2:
            return

        base = self._tile_colour(world, tile_kind)
        wall_img = self._scene_image_for_kind(tile_kind, "wall", generic=True)
        old_clip = self.screen.get_clip()
        self.screen.set_clip(rect)
        if wall_img:
            texture = self.pygame.transform.smoothscale(wall_img, (box.w, box.h))
            self.screen.blit(texture, box)
        else:
            self._fill_wall_gradient(box, base)
        veil = self.pygame.Surface((box.w, box.h), self.pygame.SRCALPHA)
        veil.fill((0, 0, 0, min(100, 22 + depth * 13 + abs(side) * 8)))
        self.screen.blit(veil, box)
        self._draw_wall_courses(wall_poly, base, front_facing=True)
        self.pygame.draw.polygon(self.screen, self._mix(GOLD_DARK, base, 0.28), wall_poly, width=2)
        if side == 0:
            label_rect = self.pygame.Rect(box.x, box.y + 8, box.w, 22)
            self._centered(label_rect, self._tile_name_for_kind(world, tile_kind, "blocked"), PAPER, self.tiny)
        self.screen.set_clip(old_clip)

    def _draw_receding_wall_cell(self, world: WorldState, rect: Any, depth: int, side: int, tile_kind: str) -> None:
        if side == 0:
            return
        points = self._cell_floor_poly(rect, depth, side)
        if side < 0:
            far_floor = points[1]
            near_floor = points[2]
        else:
            far_floor = points[0]
            near_floor = points[3]

        scale = self._depth_scale(depth)
        near_h = max(42, int(238 * scale))
        far_h = max(30, int(near_h * 0.64))
        far_top = (far_floor[0], max(rect.y + 18, far_floor[1] - far_h))
        near_top = (near_floor[0], max(rect.y + 18, near_floor[1] - near_h))
        wall_poly = [far_top, near_top, near_floor, far_floor]

        base = self._tile_colour(world, tile_kind)
        face = self._mix(base, (15, 16, 14), 0.28 + min(0.22, abs(side) * 0.05))
        highlight = self._mix(face, PAPER, 0.16)
        shadow = self._mix(face, (0, 0, 0), 0.34)

        old_clip = self.screen.get_clip()
        self.screen.set_clip(rect)
        self.pygame.draw.polygon(self.screen, face, wall_poly)
        shade = self.pygame.Surface((rect.w, rect.h), self.pygame.SRCALPHA)
        local_poly = [(x - rect.x, y - rect.y) for x, y in wall_poly]
        self.pygame.draw.polygon(shade, (0, 0, 0, min(92, 20 + depth * 12 + abs(side) * 10)), local_poly)
        self.screen.blit(shade, rect)

        for course in (0.22, 0.42, 0.62, 0.82):
            start = self._lerp_point(far_top, far_floor, course)
            end = self._lerp_point(near_top, near_floor, course)
            self.pygame.draw.line(self.screen, shadow, start, end, 1)
        for seam in (0.24, 0.5, 0.76):
            top = self._lerp_point(far_top, near_top, seam)
            bottom = self._lerp_point(far_floor, near_floor, seam)
            middle = self._lerp_point(top, bottom, 0.72)
            self.pygame.draw.line(self.screen, self._mix(shadow, highlight, 0.22), top, middle, 1)

        self.pygame.draw.line(self.screen, highlight, far_top, near_top, 1)
        self.pygame.draw.line(self.screen, self._mix(GOLD_DARK, base, 0.28), near_top, near_floor, 2)
        self.pygame.draw.line(self.screen, self._mix(GOLD_DARK, base, 0.18), far_top, far_floor, 1)
        self.screen.set_clip(old_clip)

    def _fill_wall_gradient(self, box: Any, base: tuple[int, int, int]) -> None:
        top = self._mix(base, (21, 20, 18), 0.35)
        bottom = self._mix(base, (0, 0, 0), 0.22)
        for y in range(box.h):
            colour = self._mix(top, bottom, y / max(1, box.h - 1))
            self.pygame.draw.line(self.screen, colour, (box.x, box.y + y), (box.right, box.y + y))

    def _draw_wall_courses(self, wall_poly: list[tuple[int, int]], base: tuple[int, int, int], front_facing: bool) -> None:
        top_left, top_right, bottom_right, bottom_left = wall_poly
        shadow = self._mix(base, (0, 0, 0), 0.36)
        highlight = self._mix(base, PAPER, 0.18)
        for course in (0.24, 0.43, 0.62, 0.81):
            start = self._lerp_point(top_left, bottom_left, course)
            end = self._lerp_point(top_right, bottom_right, course)
            self.pygame.draw.line(self.screen, shadow, start, end, 1)
        seams = (0.18, 0.38, 0.61, 0.82) if front_facing else (0.26, 0.52, 0.78)
        for seam in seams:
            top = self._lerp_point(top_left, top_right, seam)
            bottom = self._lerp_point(bottom_left, bottom_right, seam)
            self.pygame.draw.line(self.screen, self._mix(shadow, highlight, 0.22), top, self._lerp_point(top, bottom, 0.72), 1)

    def _draw_water_surface(self, rect: Any, points: list[tuple[int, int]], depth: int, side: int) -> None:
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        box = rect.clip(self.pygame.Rect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)))
        if box.w <= 4 or box.h <= 4:
            return
        sheen = self.pygame.Surface((box.w, box.h), self.pygame.SRCALPHA)
        for row in range(box.h):
            alpha = max(0, 34 - row // 3)
            self.pygame.draw.line(sheen, (117, 178, 206, alpha), (0, row), (box.w, row))
        wave_gap = max(8, int(18 * self._depth_scale(depth)))
        for i, yy in enumerate(range(4, box.h, wave_gap)):
            inset = 8 + (i % 2) * 10 + abs(side) * 7
            wave_rect = self.pygame.Rect(inset, yy, max(4, box.w - inset * 2), max(8, wave_gap))
            self.pygame.draw.arc(sheen, (139, 207, 226, 118), wave_rect, math.radians(184), math.radians(356), 1)
        self.screen.blit(sheen, box)
        self.pygame.draw.line(self.screen, (154, 206, 215), points[0], points[1], 1)

    def _draw_walkable_feature(self, world: WorldState, tile_kind: str, rect: Any, depth: int, side: int) -> None:
        tile_tags = set(world.grid.tile_defs.get(tile_kind, {}).get("tags") or [])
        feature_kind = ""
        if {"trees", "forest", "foliage"} & tile_tags:
            feature_kind = "trees"
        elif {"ruins", "architecture"} & tile_tags:
            feature_kind = "ruins"
        elif {"cave", "entrance"} & tile_tags:
            feature_kind = "entrance"
        if not feature_kind or depth > 4:
            return
        points = self._cell_floor_poly(rect, depth, side)
        center_x = (points[2][0] + points[3][0]) // 2
        bottom = max(point[1] for point in points) - 2
        scale = self._depth_scale(depth) * max(0.58, 1.0 - abs(side) * 0.12)
        width = max(16, int(126 * scale))
        height = max(24, int(158 * scale))
        box = self.pygame.Rect(center_x - width // 2, bottom - height, width, height)
        if not rect.colliderect(box):
            return
        box = rect.clip(box)

        if feature_kind == "trees":
            trunk = self._mix((75, 50, 27), (0, 0, 0), depth * 0.04)
            leaf = self._mix(self._tile_colour(world, tile_kind), (0, 0, 0), depth * 0.05)
            for offset in (-0.28, 0.12, 0.36):
                tx = box.centerx + int(box.w * offset)
                self.pygame.draw.line(self.screen, trunk, (tx, box.bottom), (tx + int(10 * scale), box.y + int(28 * scale)), max(1, int(5 * scale)))
                self.pygame.draw.circle(self.screen, leaf, (tx + int(12 * scale), box.y + int(24 * scale)), max(5, int(28 * scale)))
            return

        if feature_kind == "ruins":
            stone = self._mix(self._tile_colour(world, tile_kind), (0, 0, 0), 0.14 + depth * 0.04)
            cap = self._mix(PAPER, stone, 0.68)
            for offset in (-0.28, 0.28):
                col = self.pygame.Rect(box.centerx + int(box.w * offset) - max(4, box.w // 10), box.y + box.h // 4, max(8, box.w // 5), box.h * 3 // 4)
                self.pygame.draw.rect(self.screen, stone, col)
                self.pygame.draw.rect(self.screen, cap, self.pygame.Rect(col.x - 3, col.y - 5, col.w + 6, 6))
            return

        arch = self.pygame.Rect(box.x + box.w // 8, box.y + box.h // 5, box.w * 3 // 4, box.h * 4 // 5)
        cave_colour = self._tile_colour(world, tile_kind)
        self.pygame.draw.rect(self.screen, self._mix(cave_colour, (0, 0, 0), 0.22), arch, border_radius=max(3, int(10 * scale)))
        self.pygame.draw.rect(self.screen, self._mix(PAPER, cave_colour, 0.6), arch, width=max(1, int(2 * scale)), border_radius=max(3, int(10 * scale)))

    def _cell_floor_poly(self, rect: Any, depth: int, side: int) -> list[tuple[int, int]]:
        top_y, bottom_y, top_lane, bottom_lane = self._depth_band(rect, depth)
        cx = rect.centerx
        return [
            (int(cx + (side - 0.5) * top_lane), top_y),
            (int(cx + (side + 0.5) * top_lane), top_y),
            (int(cx + (side + 0.5) * bottom_lane), bottom_y),
            (int(cx + (side - 0.5) * bottom_lane), bottom_y),
        ]

    def _depth_band(self, rect: Any, depth: int) -> tuple[int, int, int, int]:
        bands = {
            5: (rect.y + 188, rect.y + 211, 35, 58),
            4: (rect.y + 211, rect.y + 240, 58, 88),
            3: (rect.y + 240, rect.y + 282, 88, 136),
            2: (rect.y + 282, rect.y + 342, 136, 218),
            1: (rect.y + 342, rect.bottom - 16, 218, 342),
        }
        return bands.get(depth, bands[1])

    def _wall_rect(self, rect: Any, depth: int, side: int) -> Any:
        points = self._cell_floor_poly(rect, depth, side)
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        floor_top = min(ys)
        floor_bottom = max(ys)
        cell_w = max(xs) - min(xs)
        scale = self._depth_scale(depth)
        if side == 0:
            width = int(690 * scale)
            height = int(286 * scale)
            x = rect.centerx - width // 2
        else:
            width = max(34, int(cell_w * 1.08))
            height = int((floor_bottom - floor_top) * (2.25 + 0.28 * abs(side)))
            x = min(xs) if side < 0 else max(xs) - width
        bottom = floor_bottom + int(8 * scale)
        y = max(rect.y + 24, bottom - max(44, height))
        wall = self.pygame.Rect(x, y, width, bottom - y)
        return rect.clip(wall)

    def _draw_side_walls(self, rect: Any, wall_img: Any | None) -> None:
        cx = rect.centerx
        left_wall = [(rect.x, rect.y), (cx - 136, rect.y + 184), (cx - 342, rect.bottom), (rect.x, rect.bottom)]
        right_wall = [(rect.right, rect.y), (cx + 136, rect.y + 184), (cx + 342, rect.bottom), (rect.right, rect.bottom)]
        if wall_img:
            left_box = self.pygame.Rect(rect.x, rect.y, 332, rect.h)
            right_box = self.pygame.Rect(rect.right - 332, rect.y, 332, rect.h)
            self._blit_scaled(wall_img, left_box)
            self._blit_scaled(wall_img, right_box)
            veil = self.pygame.Surface(self.screen.get_size(), self.pygame.SRCALPHA)
            veil.fill((0, 0, 0, 0))
            self.pygame.draw.polygon(veil, (0, 0, 0, 74), left_wall)
            self.pygame.draw.polygon(veil, (0, 0, 0, 74), right_wall)
            self.screen.blit(veil, (0, 0))
            return
        self.pygame.draw.polygon(self.screen, (48, 49, 43), left_wall)
        self.pygame.draw.polygon(self.screen, (39, 41, 38), right_wall)
        for i in range(7):
            y = rect.y + 24 + i * 54
            self.pygame.draw.line(self.screen, (75, 75, 65), (rect.x + 8, y), (cx - 120, rect.y + 184 + i * 20), 1)
            self.pygame.draw.line(self.screen, (58, 60, 55), (rect.right - 8, y), (cx + 120, rect.y + 184 + i * 20), 1)

    def _draw_floor_tiles(self, world: WorldState, rect: Any, floor_img: Any | None) -> None:
        cx = rect.centerx
        layers = {
            4: (rect.y + 206, 146, 242, 38),
            3: (rect.y + 244, 242, 370, 48),
            2: (rect.y + 292, 372, 550, 62),
            1: (rect.y + 354, 552, 820, 80),
        }
        for depth in range(4, 0, -1):
            top_y, top_w, bottom_w, height = layers[depth]
            pos = self._relative_position(world.player.position, world.player_facing, depth, 0)
            colour = self._tile_colour_at(world, pos)
            points = [
                (cx - top_w // 2, top_y),
                (cx + top_w // 2, top_y),
                (cx + bottom_w // 2, top_y + height),
                (cx - bottom_w // 2, top_y + height),
            ]
            self.pygame.draw.polygon(self.screen, self._mix(colour, (98, 83, 55), 0.28), points)
            self.pygame.draw.polygon(self.screen, (136, 125, 88), points, width=2)
            if floor_img:
                strip = self.pygame.Rect(cx - bottom_w // 2, top_y, bottom_w, height)
                image = self.pygame.transform.smoothscale(floor_img, (strip.w, strip.h))
                image.set_alpha(110)
                self.screen.blit(image, strip)
            self.pygame.draw.line(self.screen, (72, 67, 50), (cx - top_w // 2, top_y), (cx - bottom_w // 2, top_y + height), 1)
            self.pygame.draw.line(self.screen, (72, 67, 50), (cx + top_w // 2, top_y), (cx + bottom_w // 2, top_y + height), 1)

    def _draw_blocker(self, world: WorldState, rect: Any, depth: int, pos: Position) -> None:
        cx = rect.centerx
        scale = self._depth_scale(depth)
        w = int(560 * scale)
        h = int(250 * scale)
        y = int(rect.y + 118 + (4 - depth) * 54)
        wall = self.pygame.Rect(cx - w // 2, y, w, h)
        tile_kind = world.grid.tile_at(pos).kind if world.grid.in_bounds(pos) else "wall"
        wall_img = self.art.scene(tile_kind, "wall") or self.art.scene(tile_kind, "blocker")
        if wall_img:
            self._blit_scaled(wall_img, wall)
        else:
            colour = self._mix(self._tile_colour(world, tile_kind), (21, 18, 17), 0.38)
            self.pygame.draw.rect(self.screen, colour, wall, border_radius=2)
            for x in range(wall.x + 12, wall.right, max(24, int(42 * scale))):
                self.pygame.draw.line(self.screen, self._mix(colour, (180, 170, 135), 0.22), (x, wall.y + 8), (x - 18, wall.bottom - 10), 1)
        self.pygame.draw.rect(self.screen, (163, 140, 82), wall, width=2)
        self._centered(self.pygame.Rect(wall.x, wall.y + 12, wall.w, 24), self._tile_name_for_kind(world, tile_kind, "blocked"), PAPER, self.small)

    def _draw_visible_objects(self, world: WorldState, rect: Any) -> None:
        for depth in range(MAX_VIEW_DEPTH, 0, -1):
            for side in VIEW_SIDES:
                pos = self._relative_position(world.player.position, world.player_facing, depth, side)
                if not self._cell_visible(world, depth, side) or self._sight_blocked(world, pos) or not world.grid.is_walkable(pos):
                    continue
                obj = self._object_at(world, pos)
                if obj and not obj.state.get("taken"):
                    self._draw_object_billboard(rect, obj, depth, side)

    def _draw_visible_agents(self, world: WorldState, rect: Any) -> None:
        for depth in range(MAX_VIEW_DEPTH, 0, -1):
            for side in VIEW_SIDES:
                pos = self._relative_position(world.player.position, world.player_facing, depth, side)
                if not self._cell_visible(world, depth, side) or self._sight_blocked(world, pos) or not world.grid.is_walkable(pos):
                    continue
                agent = self._agent_at(world, pos)
                if agent:
                    self._draw_agent_billboard(rect, agent, depth, side)

    def _draw_object_billboard(self, rect: Any, obj: WorldObject, depth: int, side: int) -> None:
        box = self._billboard_rect(rect, depth, side, agent=False)
        sprite = self.art.object_sprite_path(obj.sprite) or self.art.object_sprite(obj.kind)
        if sprite:
            self._draw_sprite(sprite, box)
        else:
            colour = self._object_colour(obj)
            shadow = box.move(6, 9)
            self.pygame.draw.ellipse(self.screen, (0, 0, 0), self.pygame.Rect(shadow.x, shadow.bottom - 20, shadow.w, 22))
            self.pygame.draw.rect(self.screen, colour, box, border_radius=6)
            self.pygame.draw.rect(self.screen, self._mix(PAPER, colour, 0.6), box, width=2, border_radius=6)
            marker = str(obj.render.get("label") or OBJECT_MARKERS.get(obj.kind, obj.name.upper()[:8]))
            self._centered(box, marker, (22, 18, 12), self.small if depth > 1 else self.label)
        label = self.pygame.Rect(box.x - 22, box.bottom + 4, box.w + 44, 24)
        self._small_nameplate(label, obj.name[:22])

    def _draw_agent_billboard(self, rect: Any, agent: Agent, depth: int, side: int) -> None:
        box = self._billboard_rect(rect, depth, side, agent=True)
        sprite = self.art.character_sprite(agent.id, agent.emotion, agent.avatar_folder) or self._load_avatar(agent)
        self.pygame.draw.ellipse(self.screen, (0, 0, 0), self.pygame.Rect(box.x + 8, box.bottom - 22, box.w - 16, 28))
        if sprite:
            self._draw_sprite(sprite, box)
        else:
            colour = EMOTION_COLOURS.get(agent.emotion, (210, 210, 210))
            self.pygame.draw.rect(self.screen, colour, box, border_radius=8)
            self._centered(box, agent.name[0].upper(), (15, 15, 15), self.title)
        if sprite:
            outline = box.inflate(10, 10)
            self.pygame.draw.arc(self.screen, EMOTION_COLOURS.get(agent.emotion, PAPER), outline, math.radians(190), math.radians(350), 3)
        else:
            self.pygame.draw.rect(self.screen, EMOTION_COLOURS.get(agent.emotion, PAPER), box, width=3, border_radius=6)
        label = self.pygame.Rect(box.x - 34, box.bottom + 5, box.w + 68, 38)
        self._small_nameplate(label, f"{agent.name} / {agent.emotion}")

    def _draw_party_panels(self, world: WorldState, left_rect: Any, right_rect: Any) -> None:
        agents = list(world.agents.values())
        left_agents = agents[::2]
        right_agents = agents[1::2]
        self._draw_party_column(left_rect, "Front", left_agents)
        self._draw_party_column(right_rect, "Back", right_agents)

    def _draw_party_column(self, rect: Any, title: str, agents: list[Agent]) -> None:
        self._ornate_panel(rect, (31, 36, 28), title)
        y = rect.y + 28
        card_h = 128
        for agent in agents:
            self._draw_party_card(agent, self.pygame.Rect(rect.x + 7, y, rect.w - 14, card_h))
            y += card_h + 10

    def _draw_party_card(self, agent: Agent, rect: Any) -> None:
        bg = (52, 41, 29)
        self.pygame.draw.rect(self.screen, bg, rect, border_radius=4)
        self.pygame.draw.rect(self.screen, GOLD, rect, width=2, border_radius=4)
        name_rect = self.pygame.Rect(rect.x + 4, rect.y + 4, rect.w - 8, 20)
        self.pygame.draw.rect(self.screen, PAPER, name_rect, border_radius=2)
        self._centered(name_rect, agent.name, INK, self.small)
        avatar_rect = self.pygame.Rect(rect.x + 8, rect.y + 30, rect.w - 16, 58)
        avatar = self.art.character_sprite(agent.id, agent.emotion, agent.avatar_folder) or self._load_avatar(agent)
        if avatar:
            self._draw_sprite(avatar, avatar_rect)
        else:
            self.pygame.draw.rect(self.screen, EMOTION_COLOURS.get(agent.emotion, PAPER), avatar_rect, border_radius=4)
            self._centered(avatar_rect, agent.name[0].upper(), INK, self.title)
        self.pygame.draw.rect(self.screen, EMOTION_COLOURS.get(agent.emotion, PAPER), avatar_rect, width=2, border_radius=4)
        self._draw_party_stat(rect.x + 8, rect.y + 94, rect.w - 16, "HP", agent.health, (190, 56, 52))
        self._draw_party_stat(rect.x + 8, rect.y + 112, rect.w - 16, "TR", agent.social_to_player.trust, (65, 142, 205))
        if agent.active_commitment:
            label = "FOLLOW" if agent.active_commitment.type == "follow" else "TASK"
            self._line(rect.x + 76, rect.y + 94, label, (255, 241, 166), self.tiny)
        elif agent.following_player:
            self._line(rect.x + 76, rect.y + 94, "FOLLOW", (255, 241, 166), self.tiny)
        elif agent.command_target_object_id:
            self._line(rect.x + 76, rect.y + 94, "TASK", (255, 241, 166), self.tiny)

    def _draw_party_stat(self, x: int, y: int, w: int, label: str, value: float, colour: tuple[int, int, int]) -> None:
        self._line(x, y - 2, label, PAPER, self.tiny)
        bar = self.pygame.Rect(x + 28, y + 2, w - 30, 8)
        self.pygame.draw.rect(self.screen, (23, 16, 13), bar)
        fill = self.pygame.Rect(bar.x, bar.y, int(bar.w * max(0, min(100, value)) / 100), bar.h)
        self.pygame.draw.rect(self.screen, colour, fill)
        self.pygame.draw.rect(self.screen, GOLD_DARK, bar, width=1)

    def _draw_bottom_panel(self, world: WorldState, rect: Any) -> None:
        self._ornate_panel(rect, GREEN_PANEL, "Dialogue / Mozok Brain")
        self._draw_bottom_tabs(rect)
        content = self.pygame.Rect(rect.x + 20, rect.y + 62, rect.w - 40, rect.h - 82)
        if self.bottom_tab == "inventory":
            self._draw_inventory_tab(world, content)
        elif self.bottom_tab == "relations":
            self._draw_relations_tab(world, content)
        elif self.bottom_tab == "agent":
            self._draw_agent_focus_tab(world, content)
        elif self.bottom_tab == "memory":
            self._draw_memory_tab(world, content)
        else:
            self._draw_conversation_tab(world, content)
        self._line(rect.right - 176, rect.bottom - 24, "Tab switch panel", (238, 214, 161), self.tiny)

    def _draw_bottom_tabs(self, rect: Any) -> None:
        labels = [("conversation", "Conversation"), ("inventory", "Inventory"), ("relations", "Relations"), ("agent", "Agent"), ("memory", "Memory")]
        x = rect.x + 154
        y = rect.y + 12
        for tab_id, label in labels:
            tab = self.pygame.Rect(x, y, 108, 25)
            active = tab_id == self.bottom_tab
            self.pygame.draw.rect(self.screen, PAPER if active else (37, 52, 43), tab, border_radius=3)
            self.pygame.draw.rect(self.screen, GOLD_DARK if active else GOLD, tab, width=1, border_radius=3)
            self._centered(tab, label, INK if active else PAPER, self.tiny)
            x += 114

    def _draw_conversation_tab(self, world: WorldState, rect: Any) -> None:
        self._line(rect.x, rect.y, "Conversation", PAPER, self.label)
        self._line(rect.x + 170, rect.y + 2, ("Latest: " + world.last_message)[:96], (238, 214, 161), self.tiny)
        y = rect.y + 28
        chat_lines = world.chat_log[-5:] if world.chat_log else []
        if chat_lines:
            for item in chat_lines:
                name = f"{item.speaker_name}:"
                colour = self._speaker_colour(item.source)
                self._line(rect.x, y, name[:13], colour, self.small)
                for line in self._wrap(item.content, 100, 2):
                    self._line(rect.x + 92, y, line, (240, 238, 220), self.small)
                    y += 19
                y += 3
        else:
            for event in world.event_log[-5:]:
                self._line(rect.x, y, f"[{event.turn:03d}] {event.content}"[:112], (240, 238, 220), self.small)
                y += 22

    def _draw_agent_focus_tab(self, world: WorldState, rect: Any) -> None:
        agent = self._focused_agent(world)
        self._line(rect.x, rect.y, "Agent Focus", PAPER, self.label)
        if agent:
            avatar_rect = self.pygame.Rect(rect.x, rect.y + 34, 118, 138)
            avatar = self.art.character_sprite(agent.id, agent.emotion, agent.avatar_folder) or self._load_avatar(agent)
            if avatar:
                self._draw_sprite(avatar, avatar_rect)
            self.pygame.draw.rect(self.screen, GOLD, avatar_rect, width=2, border_radius=4)
            x = rect.x + 140
            self._line(x, rect.y + 28, f"{agent.name} goal: {agent.current_goal.replace('_', ' ')}"[:82], (228, 233, 215), self.small)
            self._line(x, rect.y + 49, f"Plan: {agent.current_plan}"[:82], (238, 214, 161), self.tiny)
            target_line = self._agent_target_line(world, agent)
            y = rect.y + 70
            if target_line:
                self._line(x, y, target_line[:82], (238, 214, 161), self.tiny)
                y += 17
            self._line(x, y, self._compact_state_line(agent), (238, 214, 161), self.tiny)
            y += 19
            status = self._agent_commitment_line(agent) or agent.deliberation_summary or agent.brain_broadcast or agent.brain_focus
            for line in self._wrap(status, 90, 5):
                self._line(x, y, line, (230, 231, 215), self.small)
                y += 19

    def _draw_memory_tab(self, world: WorldState, rect: Any) -> None:
        self._line(rect.x, rect.y, "Memory Notes", PAPER, self.label)
        y = rect.y + 28
        for flash in world.brain_flashes[-4:]:
            name = world.agents.get(flash.agent_id).name if world.agents.get(flash.agent_id) else flash.agent_id
            self._line(rect.x, y, f"{name}: {flash.title}"[:42], (255, 241, 166), self.small)
            y += 16
            for line in self._wrap(flash.content, 96, 2):
                self._line(rect.x + 22, y, line, (224, 229, 216), self.small)
                y += 15
            y += 4
        if not world.brain_flashes:
            self._line(rect.x, y, "No memory flashes yet.", (224, 229, 216), self.small)

    def _draw_inventory_tab(self, world: WorldState, rect: Any) -> None:
        self._line(rect.x, rect.y, "Your Inventory", PAPER, self.label)
        self._line(rect.x, rect.y + 30, inventory_label(world.player.inventory), (240, 238, 220), self.small)
        self._line(rect.x + 310, rect.y, "Nearby Objects", PAPER, self.label)
        y = rect.y + 30
        for obj in world.nearby_objects(distance=2)[:6]:
            interactions = ", ".join(obj.interactions[:4]) if obj.interactions else "no direct interaction"
            self._line(rect.x + 310, y, f"{obj.name}: {interactions}"[:76], (240, 238, 220), self.small)
            y += 21

    def _draw_relations_tab(self, world: WorldState, rect: Any) -> None:
        self._line(rect.x, rect.y, "Relationships", PAPER, self.label)
        headers = ["Toward", "Trust", "Fear", "Affinity", "Resent"]
        x_positions = [rect.x + 148, rect.x + 314, rect.x + 420, rect.x + 526, rect.x + 646]
        for x, label in zip(x_positions, headers):
            self._line(x, rect.y + 2, label, (238, 214, 161), self.tiny)
        y = rect.y + 30
        for agent in list(world.agents.values())[:5]:
            self._line(rect.x, y, agent.name[:14], (174, 220, 238), self.small)
            self._draw_social_row(agent.social_to_player, x_positions, y, "Player")
            y += 24
        y += 8
        self._line(rect.x, y, "Agent to agent", PAPER, self.label)
        y += 27
        rows = 0
        for agent in world.agents.values():
            for target in world.agents.values():
                if agent.id == target.id:
                    continue
                social = social_state_for(agent, target.id)
                self._line(rect.x, y, f"{agent.name[:9]} -> {target.name[:9]}", (224, 229, 216), self.tiny)
                self._draw_social_row(social, x_positions, y, target.name[:10], tiny=True)
                y += 18
                rows += 1
                if rows >= 6 or y > rect.bottom - 14:
                    return

    def _draw_social_row(self, social: Any, x_positions: list[int], y: int, target_label: str, tiny: bool = False) -> None:
        font = self.tiny if tiny else self.small
        values = [target_label, f"{social.trust:.0f}", f"{social.fear:.0f}", f"{social.affinity:.0f}", f"{social.resentment:.0f}"]
        colours = [(238, 238, 220), (86, 164, 230), (214, 82, 70), (112, 194, 130), (232, 142, 82)]
        for x, value, colour in zip(x_positions, values, colours):
            self._line(x, y, value, colour, font)

    def _compact_state_line(self, agent: Agent) -> str:
        return (
            f"trust {agent.social_to_player.trust:.0f} "
            f"fear {agent.social_to_player.fear:.0f} "
            f"stress {agent.needs.stress:.0f}"
        )

    def _agent_target_line(self, world: WorldState, agent: Agent) -> str:
        if agent.current_target_object_id:
            obj = world.objects.get(agent.current_target_object_id)
            return f"Target object: {obj.name if obj else agent.current_target_object_id}"
        if agent.current_target_agent_id:
            target = world.agents.get(agent.current_target_agent_id)
            return f"Target agent: {target.name if target else agent.current_target_agent_id}"
        if agent.command_target_object_id:
            obj = world.objects.get(agent.command_target_object_id)
            return f"Target object: {obj.name if obj else agent.command_target_object_id}"
        if agent.active_commitment and agent.active_commitment.target_object_id:
            obj = world.objects.get(agent.active_commitment.target_object_id)
            return f"Commit target: {obj.name if obj else agent.active_commitment.target_object_id}"
        return ""

    def _draw_dialogue_menu(self, world: WorldState, dialogue_menu: dict) -> None:
        agent = world.agents.get(dialogue_menu["agent_id"])
        if not agent:
            return
        self._dark_overlay(152)
        rect = self.pygame.Rect(302, 94, 676, 414)
        self._ornate_panel(rect, (43, 58, 48), f"Talk to {agent.name}")
        avatar_rect = self.pygame.Rect(rect.x + 24, rect.y + 46, 160, 200)
        avatar = self.art.character_sprite(agent.id, agent.emotion, agent.avatar_folder) or self._load_avatar(agent)
        if avatar:
            self._draw_sprite(avatar, avatar_rect)
        else:
            self.pygame.draw.rect(self.screen, EMOTION_COLOURS.get(agent.emotion, PAPER), avatar_rect, border_radius=5)
        self.pygame.draw.rect(self.screen, GOLD, avatar_rect, width=2, border_radius=5)
        self._line(rect.x + 206, rect.y + 52, f"{agent.role} / {agent.emotion}", PAPER, self.label)
        self._line(rect.x + 206, rect.y + 82, f"Focus: {agent.brain_focus[:50]}", (230, 232, 214), self.small)
        self._line(rect.x + 206, rect.y + 106, f"Memory: {(agent.brain_memory or 'none')[:48]}", (210, 220, 213), self.small)
        y = rect.y + 166
        for index, option in enumerate(dialogue_menu.get("options", []), start=1):
            option_rect = self.pygame.Rect(rect.x + 206, y, rect.w - 232, 48)
            self._menu_item(option_rect, f"{index}. {option['label']}")
            y += 62
        self._line(rect.x + 24, rect.bottom - 30, "1-3 choose / T or Esc close", PAPER, self.small)

    def _draw_object_menu(self, world: WorldState, object_menu: dict) -> None:
        obj = world.objects.get(str(object_menu.get("object_id", "")))
        if not obj:
            return
        self._dark_overlay(116)
        rect = self.pygame.Rect(300, 128, 680, 390)
        self._ornate_panel(rect, (43, 58, 48), obj.name)
        sprite_rect = self.pygame.Rect(rect.x + 24, rect.y + 52, 170, 190)
        sprite = self.art.object_sprite_path(obj.sprite) or self.art.object_sprite(obj.kind)
        if sprite:
            self._draw_sprite(sprite, sprite_rect)
        else:
            self.pygame.draw.rect(self.screen, self._object_colour(obj), sprite_rect, border_radius=5)
        self.pygame.draw.rect(self.screen, GOLD, sprite_rect, width=2, border_radius=5)
        tags = ", ".join(obj.tags[:6]) or obj.kind
        self._line(rect.x + 218, rect.y + 54, tags[:58], PAPER, self.small)
        y = rect.y + 92
        for index, option in enumerate(object_menu.get("options", [])[:9], start=1):
            option_rect = self.pygame.Rect(rect.x + 218, y, rect.w - 250, 48)
            label = str(option.get("label") or option.get("id") or "Interact")
            self._menu_item(option_rect, f"{index}. {label}")
            desc = str(option.get("description") or "")
            if desc:
                preview = desc.replace("{actor}", "You").replace("{target}", obj.name)
                self._line(option_rect.x + 14, option_rect.y + 27, preview[:70], (217, 219, 196), self.tiny)
            y += 60
        self._line(rect.x + 24, rect.bottom - 28, "1-9 choose / E or Esc close", PAPER, self.small)

    def _draw_model_settings(self, world: WorldState, settings_ui: dict) -> None:
        self._dark_overlay(148)
        rect = self.pygame.Rect(250, 78, 780, 560)
        self._ornate_panel(rect, (43, 70, 57), "LLM Model Roles")
        selected = int(settings_ui.get("selected", 0)) % len(MODEL_ROLES)
        editing = bool(settings_ui.get("editing"))
        draft = dict(settings_ui.get("draft") or {})
        available = list(settings_ui.get("available") or [])
        self._line(rect.x + 34, rect.y + 42, f"Scenario: {world.scenario_title}", PAPER, self.small)
        self._line(rect.x + 34, rect.y + 66, "Pick which model handles each kind of thinking.", (224, 229, 216), self.small)

        y = rect.y + 108
        for index, role in enumerate(MODEL_ROLES):
            row = self.pygame.Rect(rect.x + 34, y, rect.w - 68, 42)
            active = index == selected
            self.pygame.draw.rect(self.screen, PAPER if active else (34, 61, 48), row, border_radius=4)
            self.pygame.draw.rect(self.screen, GOLD if active else GOLD_DARK, row, width=2 if active else 1, border_radius=4)
            role_colour = INK if active else PAPER
            model_colour = (45, 35, 22) if active else (238, 238, 220)
            model = str(draft.get(role) or "(server default)")
            cursor = "_" if active and editing and (self.pygame.time.get_ticks() // 450) % 2 == 0 else ""
            self._line(row.x + 14, row.y + 11, role, role_colour, self.label)
            self._line(row.x + 178, row.y + 12, (model + cursor)[:62], model_colour, self.small)
            y += 48

        status = str(settings_ui.get("status") or "")
        self._line(rect.x + 34, rect.bottom - 86, status[:92], (238, 214, 161), self.small)
        if available:
            self._line(rect.x + 34, rect.bottom - 62, ("Known: " + ", ".join(available[:5]))[:96], (205, 215, 198), self.tiny)
        else:
            self._line(rect.x + 34, rect.bottom - 62, "Known: none yet. R tries local Ollama discovery; typing any model name also works.", (205, 215, 198), self.tiny)
        self._line(rect.x + 34, rect.bottom - 32, "Up/Down select   Enter edit   Tab cycle   A all   P powerful   H helper   Delete clear   Ctrl+S save   R refresh   Esc", PAPER, self.tiny)

    def _draw_text_chat(self, world: WorldState, text_chat: dict) -> None:
        self._dark_overlay(72)
        target_ids = list(text_chat.get("target_ids", []))
        agents = [world.agents[agent_id] for agent_id in target_ids if agent_id in world.agents]
        names = ", ".join(agent.name for agent in agents) or "nobody"
        mode = str(text_chat.get("mode", "group"))
        title = str(text_chat.get("title") or ("Group Chat" if mode == "group" else "Talk"))
        rect = self.pygame.Rect(170, 398, 940, 306)
        self._ornate_panel(rect, GREEN_PANEL, title)
        lead = f"Facing: {names}" if mode == "direct" else f"Nearby: {names}"
        self._line(rect.x + 28, rect.y + 28, lead, PAPER, self.small)

        portrait_rect = self.pygame.Rect(rect.x + 28, rect.y + 58, 172, 206)
        lead_agent = agents[0] if agents else None
        if lead_agent:
            avatar = self.art.character_sprite(lead_agent.id, lead_agent.emotion, lead_agent.avatar_folder) or self._load_avatar(lead_agent)
            if avatar:
                self._draw_sprite(avatar, portrait_rect)
            else:
                self.pygame.draw.rect(self.screen, EMOTION_COLOURS.get(lead_agent.emotion, PAPER), portrait_rect, border_radius=5)
            self.pygame.draw.rect(self.screen, GOLD, portrait_rect, width=2, border_radius=5)
            self._small_nameplate(self.pygame.Rect(portrait_rect.x, portrait_rect.bottom + 6, portrait_rect.w, 24), f"{lead_agent.name} / {lead_agent.emotion}")

        dialogue_rect = self.pygame.Rect(rect.x + 224, rect.y + 54, rect.w - 252, 116)
        self.pygame.draw.rect(self.screen, (35, 67, 52), dialogue_rect, border_radius=4)
        self.pygame.draw.rect(self.screen, GOLD_DARK, dialogue_rect, width=2, border_radius=4)
        rows = self._chat_rows_for_targets(world, target_ids)
        latest = self._latest_chat_line_for_targets(world, target_ids)
        scroll = max(0, int(text_chat.get("scroll", 0)))
        if scroll and rows:
            max_rows = 5
            end = max(0, len(rows) - scroll)
            start = max(0, end - max_rows)
            y = dialogue_rect.y + 16
            for speaker, text, colour in rows[start:end]:
                if speaker:
                    self._line(dialogue_rect.x + 16, y, speaker[:12], colour, self.small)
                self._line(dialogue_rect.x + 120, y, text, (240, 238, 220), self.small)
                y += 20
            self._line(dialogue_rect.right - 150, dialogue_rect.y + 10, "history scroll", (238, 214, 161), self.tiny)
        elif latest:
            speaker_colour = self._speaker_colour(latest.source)
            self._line(dialogue_rect.x + 18, dialogue_rect.y + 14, f"{latest.speaker_name}:", speaker_colour, self.label)
            y = dialogue_rect.y + 46
            for line in self._wrap(latest.content, 78, 3):
                self._line(dialogue_rect.x + 18, y, line, (248, 244, 220), self.font)
                y += 24
        else:
            self._line(dialogue_rect.x + 18, dialogue_rect.y + 48, "Say something.", (248, 244, 220), self.font)

        effects = list(text_chat.get("effects") or [])
        effects_rect = self.pygame.Rect(rect.x + 224, dialogue_rect.bottom + 8, rect.w - 252, 38)
        self.pygame.draw.rect(self.screen, (27, 52, 43), effects_rect, border_radius=4)
        self.pygame.draw.rect(self.screen, GOLD_DARK, effects_rect, width=1, border_radius=4)
        if effects:
            y = effects_rect.y + 6
            for effect in effects[-2:]:
                self._line(effects_rect.x + 12, y, effect[:96], (238, 214, 161), self.tiny)
                y += 17
        else:
            self._line(effects_rect.x + 12, effects_rect.y + 13, "Social effects will appear here after each line.", (205, 215, 198), self.tiny)

        input_rect = self.pygame.Rect(rect.x + 224, rect.bottom - 82, rect.w - 252, 46)
        self.pygame.draw.rect(self.screen, (250, 240, 188), input_rect, border_radius=3)
        self.pygame.draw.rect(self.screen, GOLD_DARK, input_rect, width=2, border_radius=3)
        text = str(text_chat.get("text", ""))
        cursor = "_" if (self.pygame.time.get_ticks() // 450) % 2 == 0 else ""
        self._line(input_rect.x + 14, input_rect.y + 13, (text + cursor)[-88:], INK, self.label)
        hint = "Type / Enter send / Up Down scroll / Esc close" if mode == "direct" else "Type / Enter send to adjacent agents / Up Down scroll / Esc close"
        self._line(input_rect.x, rect.bottom - 26, hint, PAPER, self.small)

    def _chat_lines_for_targets(self, world: WorldState, target_ids: list[str]) -> list[Any]:
        target_set = set(target_ids)
        if not target_set:
            return world.chat_log
        result = []
        for line in world.chat_log:
            if line.speaker_id == "player":
                if not line.audience_ids or target_set.intersection(line.audience_ids):
                    result.append(line)
            elif line.speaker_id in target_set:
                result.append(line)
        return result

    def _latest_chat_line_for_targets(self, world: WorldState, target_ids: list[str]) -> Any | None:
        lines = self._chat_lines_for_targets(world, target_ids)
        return lines[-1] if lines else None

    def _chat_rows_for_targets(self, world: WorldState, target_ids: list[str]) -> list[tuple[str, str, tuple[int, int, int]]]:
        rows: list[tuple[str, str, tuple[int, int, int]]] = []
        for line in self._chat_lines_for_targets(world, target_ids):
            colour = self._speaker_colour(line.source)
            wrapped = self._wrap(line.content, 82, 12)
            for index, text in enumerate(wrapped):
                rows.append((f"{line.speaker_name}:" if index == 0 else "", text, colour))
            rows.append(("", "", colour))
        return rows

    def _speaker_colour(self, source: str) -> tuple[int, int, int]:
        if source == "player":
            return (255, 241, 166)
        if source == "system":
            return (238, 214, 161)
        return (174, 220, 238)

    def _draw_agent_dossier(self, world: WorldState, dossier: dict) -> None:
        agent = world.agents.get(dossier.get("agent_id", ""))
        if not agent:
            return
        self._dark_overlay(148)
        rect = self.pygame.Rect(214, 54, 852, 590)
        self._ornate_panel(rect, (43, 70, 57), f"{agent.name} Dossier")

        avatar_rect = self.pygame.Rect(rect.x + 24, rect.y + 46, 154, 190)
        avatar = self.art.character_sprite(agent.id, agent.emotion, agent.avatar_folder) or self._load_avatar(agent)
        if avatar:
            self._draw_sprite(avatar, avatar_rect)
        else:
            self.pygame.draw.rect(self.screen, EMOTION_COLOURS.get(agent.emotion, PAPER), avatar_rect, border_radius=5)
        self.pygame.draw.rect(self.screen, GOLD, avatar_rect, width=2, border_radius=5)

        lines = self._agent_dossier_lines(world, agent)
        scroll = max(0, int(dossier.get("scroll", 0)))
        visible = lines[scroll : scroll + 25]

        x = rect.x + 204
        y = rect.y + 44
        for kind, text in visible:
            if kind == "header":
                self._line(x, y, text, PAPER, self.label)
                y += 25
            elif kind == "subtle":
                self._line(x, y, text, (205, 215, 198), self.tiny)
                y += 16
            else:
                for wrapped in self._wrap(text, 76, 3):
                    self._line(x, y, wrapped, (238, 238, 220), self.small)
                    y += 19
            if y > rect.bottom - 40:
                break

        self._line(rect.x + 24, rect.bottom - 30, "I / Esc close   Up/Down scroll", PAPER, self.small)
        count_text = f"{min(scroll + len(visible), len(lines))}/{len(lines)}"
        self._line(rect.right - 72, rect.bottom - 30, count_text, PAPER, self.small)

    def _agent_dossier_lines(self, world: WorldState, agent: Agent) -> list[tuple[str, str]]:
        lines: list[tuple[str, str]] = []
        lines.append(("header", "Profile"))
        lines.append(("body", f"{agent.role}. Personality: {agent.personality}"))
        if agent.traits:
            top_traits = sorted(agent.traits.items(), key=lambda item: item[1], reverse=True)[:5]
            lines.append(("body", "Traits: " + ", ".join(f"{name} {value:.2f}" for name, value in top_traits)))
        if agent.values:
            lines.append(("body", "Values: " + ", ".join(agent.values[:5])))
        if agent.fears:
            lines.append(("body", "Fears: " + ", ".join(agent.fears[:5])))
        if agent.skills:
            lines.append(("body", "Skills: " + ", ".join(agent.skills[:5])))
        if agent.voice:
            voice = ", ".join(str(value) for value in agent.voice.values())
            lines.append(("body", f"Voice: {voice}"))
        if agent.stress_response:
            lines.append(("body", "Stress response: " + ", ".join(agent.stress_response[:4])))
        if agent.temptations:
            lines.append(("body", "Temptations: " + ", ".join(agent.temptations[:4])))
        flags = ", ".join(agent.status_flags) if agent.status_flags else "none"
        lines.append(("body", f"Emotion: {agent.emotion} intensity {agent.emotion_intensity:.2f}. Health {agent.health:.0f}. Status: {flags}. Current goal: {agent.current_goal.replace('_', ' ')}."))
        lines.append(("subtle", f"Position {agent.position.x},{agent.position.y}. Last action: {agent.last_action}."))

        lines.append(("header", "Body And Social State"))
        lines.append(("body", f"Hunger {agent.needs.hunger:.0f}, thirst {agent.needs.thirst:.0f}, fatigue {agent.needs.fatigue:.0f}, stress {agent.needs.stress:.0f}, social need {agent.needs.social:.0f}, curiosity {agent.needs.curiosity:.0f}."))
        lines.append(("body", f"Toward player: trust {agent.social_to_player.trust:.0f}, fear {agent.social_to_player.fear:.0f}, affinity {agent.social_to_player.affinity:.0f}, resentment {agent.social_to_player.resentment:.0f}."))

        lines.append(("header", "Commitments"))
        commitment = self._agent_commitment_line(agent)
        if commitment:
            lines.append(("body", commitment))
        elif agent.command_target_object_id:
            target = world.objects.get(agent.command_target_object_id)
            lines.append(("body", f"Accepted task: move toward {target.name if target else agent.command_target_object_id}."))
        else:
            lines.append(("body", "No active player commitment. Agent is following autonomous goals."))
        if agent.command_interrupt_reason:
            lines.append(("body", f"Last interruption: {agent.command_interrupt_reason}"))

        lines.append(("header", "Working Thought"))
        lines.append(("body", f"World pressure: {pressure_summary(world.pressure)}"))
        lines.append(("body", f"Current plan: {agent.current_plan}"))
        target_line = self._agent_target_line(world, agent)
        if target_line:
            lines.append(("body", target_line))
        lines.append(("body", f"Deliberation: {agent.deliberation_summary}"))
        lines.append(("body", f"Focus: {agent.brain_focus}"))
        if agent.brain_memory:
            lines.append(("body", f"Memory in working context: {agent.brain_memory}"))
        lines.append(("body", f"Broadcast: {agent.brain_broadcast}"))
        lines.append(("subtle", f"Focus score {agent.brain_focus_score:.2f}. Risk/self-model note: {agent.brain_risk}."))

        lines.append(("header", "Inventory"))
        lines.append(("body", inventory_label(agent.inventory)))
        for item_id in sorted(set(agent.inventory)):
            caps = ", ".join(sorted(item_capabilities(item_id))[:8])
            if caps:
                lines.append(("subtle", f"{item_name(item_id)}: {caps}"))

        lines.append(("header", "Known Memories"))
        if agent.memory_snippets:
            for memory in agent.memory_snippets:
                lines.append(("body", f"- {memory}"))
        else:
            lines.append(("body", "No long-term memory snippets loaded."))

        lines.append(("header", "Recent Claims Heard"))
        claims = [claim for claim in world.claim_log[-10:] if claim.listener_id == agent.id or claim.listener_id == "group"]
        if claims:
            for claim in claims[-6:]:
                target = claim.target_object_id or claim.object or "no target"
                lines.append(("body", f"- {claim.speaker_id} claimed: {claim.text} [type: {claim.claim_type}; target: {target}; {claim.truth_status}, {claim.confidence:.2f}]"))
        else:
            lines.append(("body", "No explicit claims recorded for this agent yet."))

        lines.append(("header", "Recent Beliefs From Perception"))
        beliefs = [belief for belief in world.agent_beliefs[-12:] if belief.agent_id == agent.id]
        if beliefs:
            for belief in beliefs[-5:]:
                tags = ",".join(belief.emotional_tags[:3]) or "plain"
                lines.append(("body", f"- {belief.subject} {belief.predicate} {belief.object}. {belief.source}, {belief.confidence:.2f}, tags={tags}."))
        else:
            lines.append(("body", "No structured perception beliefs recorded yet."))

        lines.append(("header", "Recent Dialogue"))
        chat = [line for line in world.chat_log[-12:] if line.speaker_id in {agent.id, "player"}]
        if chat:
            for line in chat[-6:]:
                lines.append(("body", f"{line.speaker_name}: {line.content}"))
        else:
            lines.append(("body", "No recent direct or group chat lines."))

        lines.append(("header", "Recent Brain Notes"))
        flashes = [flash for flash in world.brain_flashes[-10:] if flash.agent_id == agent.id]
        if flashes:
            for flash in flashes[-5:]:
                lines.append(("body", f"- {flash.title}: {flash.content}"))
        else:
            lines.append(("body", "No recent brain notes for this agent."))
        return lines

    def _draw_minimap(self, world: WorldState, rect: Any) -> None:
        self.pygame.draw.rect(self.screen, (19, 19, 17), rect, border_radius=4)
        self.pygame.draw.rect(self.screen, GOLD_DARK, rect, width=2, border_radius=4)
        tile = min((rect.w - 18) // world.grid.width, (rect.h - 28) // world.grid.height)
        ox = rect.x + 9
        oy = rect.y + 20
        self._line(rect.x + 10, rect.y + 5, "MAP", PAPER, self.tiny)
        for y in range(world.grid.height):
            for x in range(world.grid.width):
                map_rect = self.pygame.Rect(ox + x * tile, oy + y * tile, tile - 1, tile - 1)
                kind = world.grid.tiles[y][x].kind
                self.pygame.draw.rect(self.screen, self._tile_colour(world, kind), map_rect)
        for obj in world.objects.values():
            self._draw_minimap_dot(ox, oy, tile, obj.position, GOLD)
        for agent in world.agents.values():
            self._draw_minimap_dot(ox, oy, tile, agent.position, EMOTION_COLOURS.get(agent.emotion, PAPER))
        p = world.player.position
        px = ox + p.x * tile + tile // 2
        py = oy + p.y * tile + tile // 2
        dx, dy = FACING_DELTAS[world.player_facing]
        arrow = [(px + dx * 6, py + dy * 6), (px - dy * 4, py + dx * 4), (px + dy * 4, py - dx * 4)]
        self.pygame.draw.polygon(self.screen, (255, 255, 250), arrow)

    def _draw_view_title(self, world: WorldState, rect: Any) -> None:
        title_rect = self.pygame.Rect(rect.x + 18, rect.y + 10, 330, 28)
        self.pygame.draw.rect(self.screen, (17, 37, 31), title_rect, border_radius=4)
        self.pygame.draw.rect(self.screen, GOLD, title_rect, width=2, border_radius=4)
        front = self._relative_position(world.player.position, world.player_facing, 1, 0)
        front_name = self._tile_name(world, front)
        self._line(title_rect.x + 12, title_rect.y + 4, f"{front_name} / {world.player_facing.upper()}", PAPER, self.small)

    def _draw_corner_status(self, world: WorldState) -> None:
        rect = self.pygame.Rect(990, 10, 116, 28)
        self.pygame.draw.rect(self.screen, (62, 45, 20), rect, border_radius=4)
        self.pygame.draw.rect(self.screen, GOLD, rect, width=2, border_radius=4)
        self._centered(rect, f"{world.turn:02d}.{world.player.position.x}{world.player.position.y}", PAPER, self.small)

    def _draw_player_inventory(self, world: WorldState) -> None:
        rect = self.pygame.Rect(760, 10, 220, 28)
        self.pygame.draw.rect(self.screen, (17, 37, 31), rect, border_radius=4)
        self.pygame.draw.rect(self.screen, GOLD_DARK, rect, width=1, border_radius=4)
        text = f"Inv: {inventory_label(world.player.inventory)}"
        self._line(rect.x + 8, rect.y + 5, text[:34], PAPER, self.tiny)

    def _draw_debug(self, world: WorldState) -> None:
        rect = self.pygame.Rect(178, 48, 560, 236)
        self.pygame.draw.rect(self.screen, (0, 0, 0), rect, border_radius=6)
        self.pygame.draw.rect(self.screen, GOLD, rect, width=1, border_radius=6)
        y = rect.y + 14
        self._line(rect.x + 14, y, "DEBUG: world state / MOZOK-facing signals", PAPER, self.small)
        y += 24
        self._line(rect.x + 14, y, f"Player pos: {world.player.position.x},{world.player.position.y} facing={world.player_facing} inv={inventory_label(world.player.inventory)}", (230, 230, 230), self.small)
        y += 22
        for agent in world.agents.values():
            text = (
                f"{agent.id}: pos={agent.position.x},{agent.position.y} emotion={agent.emotion} "
                f"hp={agent.health:.0f} flags={','.join(agent.status_flags) or '-'} h={agent.needs.hunger:.0f} t={agent.needs.thirst:.0f} s={agent.needs.stress:.0f} action={agent.last_action}"
            )
            self._line(rect.x + 14, y, text[:84], (210, 210, 210), self.mono)
            y += 20

    def _billboard_rect(self, rect: Any, depth: int, side: int, agent: bool) -> Any:
        scale = self._depth_scale(depth)
        side_scale = max(0.66, 1.0 - abs(side) * 0.12)
        w = int((168 if agent else 132) * scale * side_scale)
        h = int((228 if agent else 106) * scale * side_scale)
        points = self._cell_floor_poly(rect, depth, side)
        center_x = (points[2][0] + points[3][0]) // 2
        bottom = max(point[1] for point in points) - int(8 * scale)
        return self.pygame.Rect(center_x - w // 2, bottom - h, w, h)

    def _depth_scale(self, depth: int) -> float:
        return {1: 1.0, 2: 0.72, 3: 0.52, 4: 0.38, 5: 0.28}[depth]

    def _agent_commitment_line(self, agent: Agent) -> str:
        if agent.active_commitment:
            commitment = agent.active_commitment
            parts = [f"{agent.name} commitment: {commitment.type}"]
            if commitment.goal:
                parts.append(commitment.goal)
            if commitment.target_object_id:
                parts.append(f"target={commitment.target_object_id}")
            if commitment.constraints:
                concise = ", ".join(f"{key}={value}" for key, value in list(commitment.constraints.items())[:3])
                parts.append(f"constraints: {concise}")
            return ". ".join(parts) + "."
        if agent.following_player:
            return f"{agent.name} agreed to follow you. They will try to stay on a neighbouring tile."
        if agent.command_target_object_id:
            return f"{agent.name} accepted a task: {agent.command_reason or 'moving to a requested place'}."
        return ""

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

    def _scene_image_ahead(self, world: WorldState, layer: str) -> Any | None:
        front = self._relative_position(world.player.position, world.player_facing, 1, 0)
        tile_kind = world.grid.tile_at(front).kind if world.grid.in_bounds(front) else "wall"
        return self.art.scene(tile_kind, layer)

    def _scene_image_for_kind(self, tile_kind: str, layer: str, generic: bool) -> Any | None:
        candidates = [
            ("tiles", tile_kind, f"{layer}.png"),
            ("scene", f"{tile_kind}_{layer}.png"),
        ]
        if generic:
            candidates.append(("scene", f"{layer}.png"))
        return self.art.first(candidates)

    def _sight_blocked(self, world: WorldState, pos: Position) -> bool:
        if not world.grid.in_bounds(pos):
            return True
        tile = world.grid.tile_at(pos)
        tile_def = world.grid.tile_defs.get(tile.kind, {})
        if "blocks_sight" in tile_def:
            return bool(tile_def.get("blocks_sight"))
        tags = set(tile.tags or tile_def.get("tags") or [])
        if "transparent" in tags or "water" in tags:
            return False
        return not tile.walkable or tile.kind == "wall"

    def _front_wall_face_visible(self, world: WorldState, depth: int, side: int) -> bool:
        if depth == 1:
            return True
        near_pos = self._relative_position(world.player.position, world.player_facing, depth - 1, side)
        return self._cell_visible(world, depth - 1, side) and not self._sight_blocked(world, near_pos)

    def _side_wall_face_visible(self, world: WorldState, depth: int, side: int) -> bool:
        if side == 0:
            return False
        toward_center = side - (1 if side > 0 else -1)
        open_pos = self._relative_position(world.player.position, world.player_facing, depth, toward_center)
        return self._cell_visible(world, depth, toward_center) and not self._sight_blocked(world, open_pos)

    def _cell_visible(self, world: WorldState, depth: int, side: int) -> bool:
        for step in range(1, depth):
            if side == 0:
                blockers = [0]
            elif abs(side) == 1:
                blockers = [0, side]
            else:
                near_side = 1 if side > 0 else -1
                blockers = [0, near_side, side]
            if any(self._sight_blocked(world, self._relative_position(world.player.position, world.player_facing, step, blocker)) for blocker in blockers):
                return False
        return True

    def _relative_position(self, origin: Position, facing: str, depth: int, side: int) -> Position:
        fx, fy = FACING_DELTAS[facing]
        rx, ry = RIGHT_DELTAS[facing]
        return Position(origin.x + fx * depth + rx * side, origin.y + fy * depth + ry * side)

    def _tile_colour_at(self, world: WorldState, pos: Position) -> tuple[int, int, int]:
        if not world.grid.in_bounds(pos):
            return TILE_COLOURS["wall"]
        return self._tile_colour(world, world.grid.tile_at(pos).kind)

    def _tile_name(self, world: WorldState, pos: Position) -> str:
        if not world.grid.in_bounds(pos):
            return "edge of map"
        tile = world.grid.tile_at(pos)
        return tile.label or self._tile_name_for_kind(world, tile.kind, "unknown ground")

    def _tile_name_for_kind(self, world: WorldState, kind: str, fallback: str = "tile") -> str:
        tile_def = world.grid.tile_defs.get(kind, {})
        render = tile_def.get("render") if isinstance(tile_def.get("render"), dict) else {}
        return str(tile_def.get("label") or render.get("label") or TILE_NAMES.get(kind, fallback))

    def _tile_colour(self, world: WorldState, kind: str) -> tuple[int, int, int]:
        tile_def = world.grid.tile_defs.get(kind, {})
        render = tile_def.get("render") if isinstance(tile_def.get("render"), dict) else {}
        raw = render.get("colour") or render.get("color") or tile_def.get("colour") or tile_def.get("color")
        if isinstance(raw, list) and len(raw) >= 3:
            return (int(raw[0]), int(raw[1]), int(raw[2]))
        tags = set(tile_def.get("tags") or [])
        if "water" in tags:
            return TILE_COLOURS["water"]
        if "blocked" in tags or not bool(tile_def.get("walkable", True)):
            return TILE_COLOURS["wall"]
        return TILE_COLOURS.get(kind, (80, 80, 80))

    def _object_colour(self, obj: WorldObject) -> tuple[int, int, int]:
        raw = obj.render.get("colour") or obj.render.get("color")
        if isinstance(raw, list) and len(raw) >= 3:
            return (int(raw[0]), int(raw[1]), int(raw[2]))
        for tag in obj.tags:
            if tag in OBJECT_COLOURS:
                return OBJECT_COLOURS[tag]
        if obj.object_type in OBJECT_COLOURS:
            return OBJECT_COLOURS[obj.object_type]
        return (190, 176, 126)

    def _tile_has_tag(self, world: WorldState, kind: str, tag: str) -> bool:
        return tag in set(world.grid.tile_defs.get(kind, {}).get("tags") or [])

    def _sync_art_pack(self, world: WorldState) -> None:
        if world.art_pack and world.art_pack != self.art.pack_name:
            self.art = ArtAssets(self.pygame, self.base_dir, world.art_pack)

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

    def _ornate_panel(self, rect: Any, colour: tuple[int, int, int], title: str = "") -> None:
        self.pygame.draw.rect(self.screen, (37, 25, 15), rect, border_radius=5)
        self.pygame.draw.rect(self.screen, GOLD_DARK, rect, width=5, border_radius=5)
        inner = rect.inflate(-10, -10)
        self.pygame.draw.rect(self.screen, colour, inner, border_radius=3)
        self.pygame.draw.rect(self.screen, GOLD, inner, width=2, border_radius=3)
        if title:
            title_rect = self.pygame.Rect(rect.x + 12, rect.y - 1, min(rect.w - 24, 310), 26)
            self.pygame.draw.rect(self.screen, PAPER, title_rect, border_radius=3)
            self.pygame.draw.rect(self.screen, GOLD_DARK, title_rect, width=2, border_radius=3)
            self._centered(title_rect, title, INK, self.small)

    def _menu_item(self, rect: Any, text: str) -> None:
        self.pygame.draw.rect(self.screen, PAPER, rect, border_radius=4)
        self.pygame.draw.rect(self.screen, GOLD_DARK, rect, width=2, border_radius=4)
        self._line(rect.x + 14, rect.y + 13, text, INK, self.label)

    def _small_nameplate(self, rect: Any, text: str) -> None:
        self.pygame.draw.rect(self.screen, (31, 24, 17), rect, border_radius=4)
        self.pygame.draw.rect(self.screen, GOLD_DARK, rect, width=2, border_radius=4)
        self._centered(rect, text, PAPER, self.tiny)

    def _draw_sprite(self, image: Any, rect: Any) -> None:
        src_w, src_h = image.get_size()
        if src_w <= 0 or src_h <= 0:
            return
        scale = min(rect.w / src_w, rect.h / src_h)
        size = (max(1, int(src_w * scale)), max(1, int(src_h * scale)))
        scaled = self.pygame.transform.smoothscale(image, size)
        self.screen.blit(scaled, (rect.centerx - size[0] // 2, rect.bottom - size[1]))

    def _blit_scaled(self, image: Any, rect: Any) -> None:
        scaled = self.pygame.transform.smoothscale(image, (rect.w, rect.h))
        self.screen.blit(scaled, rect)

    def _draw_minimap_dot(self, ox: int, oy: int, tile: int, pos: Position, colour: tuple[int, int, int]) -> None:
        cx = ox + pos.x * tile + tile // 2
        cy = oy + pos.y * tile + tile // 2
        self.pygame.draw.circle(self.screen, colour, (cx, cy), max(2, tile // 2))

    def _draw_view_shadow(self, rect: Any) -> None:
        self.pygame.draw.rect(self.screen, (0, 0, 0), rect, width=3)
        self.pygame.draw.rect(self.screen, GOLD_DARK, rect.inflate(-4, -4), width=2)
        shade = self.pygame.Surface((rect.w, rect.h), self.pygame.SRCALPHA)
        self.pygame.draw.rect(shade, (0, 0, 0, 72), self.pygame.Rect(0, 0, rect.w, 18))
        self.pygame.draw.rect(shade, (0, 0, 0, 90), self.pygame.Rect(0, rect.h - 22, rect.w, 22))
        self.pygame.draw.rect(shade, (0, 0, 0, 65), self.pygame.Rect(0, 0, 18, rect.h))
        self.pygame.draw.rect(shade, (0, 0, 0, 65), self.pygame.Rect(rect.w - 18, 0, 18, rect.h))
        self.screen.blit(shade, rect)

    def _dark_overlay(self, alpha: int) -> None:
        overlay = self.pygame.Surface(self.screen.get_size(), self.pygame.SRCALPHA)
        overlay.fill((0, 0, 0, alpha))
        self.screen.blit(overlay, (0, 0))

    def _centered(self, rect: Any, text: str, colour: tuple[int, int, int], font: Any) -> None:
        surf = font.render(text, True, colour)
        self.screen.blit(surf, (rect.centerx - surf.get_width() // 2, rect.centery - surf.get_height() // 2))

    def _line(self, x: int, y: int, text: str, colour: tuple[int, int, int], font: Any | None = None) -> None:
        self.screen.blit((font or self.font).render(str(text), True, colour), (x, y))

    def _mix(self, a: tuple[int, int, int], b: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
        t = max(0.0, min(1.0, amount))
        return tuple(int(a[i] * (1.0 - t) + b[i] * t) for i in range(3))

    def _lerp_point(self, a: tuple[int, int], b: tuple[int, int], amount: float) -> tuple[int, int]:
        t = max(0.0, min(1.0, amount))
        return (int(a[0] * (1.0 - t) + b[0] * t), int(a[1] * (1.0 - t) + b[1] * t))

    def _wrap(self, text: str, width: int, limit: int) -> list[str]:
        words = str(text).split()
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
