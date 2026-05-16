from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from mozok_game.engine.models import Agent, Position, WorldObject
from mozok_game.engine.world_state import WorldState
from mozok_game.ui.art_assets import ArtAssets

TILE_COLOURS: dict[str, tuple[int, int, int]] = {
    "sand": (174, 142, 86),
    "grass": (56, 116, 66),
    "forest": (25, 72, 43),
    "water": (38, 83, 128),
    "rock": (64, 62, 66),
    "camp": (124, 78, 43),
    "cave": (43, 38, 50),
    "ruins": (92, 91, 87),
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
    "neutral": (194, 194, 184),
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

OBJECT_COLOURS = {
    "water_source": (72, 159, 212),
    "food_crate": (166, 105, 52),
    "campfire": (232, 118, 54),
    "cave_entrance": (84, 78, 104),
    "broken_radio": (120, 134, 145),
    "shelter": (115, 139, 84),
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
        self.avatar_cache: dict[tuple[str, str], Any] = {}

    def draw(self, world: WorldState, dialogue_menu: dict | None = None, text_chat: dict | None = None) -> None:
        self.screen.fill((10, 9, 7))
        left_rect = self.pygame.Rect(8, 8, 150, 436)
        view_rect = self.pygame.Rect(168, 8, 944, 436)
        right_rect = self.pygame.Rect(1122, 8, 150, 436)
        bottom_rect = self.pygame.Rect(168, 452, 944, 260)

        self._draw_first_person_view(world, view_rect)
        self._draw_party_panels(world, left_rect, right_rect)
        self._draw_bottom_panel(world, bottom_rect)
        self._draw_corner_status(world)

        if self.debug:
            self._draw_debug(world)
        if dialogue_menu:
            self._draw_dialogue_menu(world, dialogue_menu)
        if text_chat:
            self._draw_text_chat(world, text_chat)
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
        tile_kind = world.grid.tile_at(current).kind if world.grid.in_bounds(current) else "grass"
        ground = TILE_COLOURS.get(tile_kind, TILE_COLOURS["grass"])
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
                tile_kind = world.grid.tile_at(pos).kind if world.grid.in_bounds(pos) else "rock"
                if self._side_wall_face_visible(world, depth, side):
                    self._draw_receding_wall_cell(rect, depth, side, tile_kind)
        for depth in range(MAX_VIEW_DEPTH, 0, -1):
            for side in VIEW_SIDES:
                pos = self._relative_position(world.player.position, world.player_facing, depth, side)
                if not self._sight_blocked(world, pos):
                    continue
                tile_kind = world.grid.tile_at(pos).kind if world.grid.in_bounds(pos) else "rock"
                if self._front_wall_face_visible(world, depth, side):
                    self._draw_front_wall_face(rect, depth, side, tile_kind)

    def _draw_floor_cell(self, world: WorldState, rect: Any, depth: int, side: int, pos: Position) -> None:
        points = self._cell_floor_poly(rect, depth, side)
        tile_kind = world.grid.tile_at(pos).kind if world.grid.in_bounds(pos) else "grass"
        base = TILE_COLOURS.get(tile_kind, TILE_COLOURS["grass"])
        shade = self._mix(base, (18, 21, 16), 0.12 + depth * 0.035)
        if side:
            shade = self._mix(shade, (0, 0, 0), min(0.16, abs(side) * 0.06))
        self.pygame.draw.polygon(self.screen, shade, points)

        image = None if tile_kind == "water" else self._scene_image_for_kind(tile_kind, "floor", generic=True)
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
        if tile_kind == "water":
            self._draw_water_surface(rect, points, depth, side)
        if side == 0:
            self.pygame.draw.line(self.screen, self._mix(edge, (0, 0, 0), 0.45), points[0], points[3], 1)
            self.pygame.draw.line(self.screen, self._mix(edge, (0, 0, 0), 0.45), points[1], points[2], 1)
        self._draw_walkable_feature(tile_kind, rect, depth, side)

    def _draw_wall_cell(self, world: WorldState, rect: Any, depth: int, side: int, pos: Position) -> None:
        tile_kind = world.grid.tile_at(pos).kind if world.grid.in_bounds(pos) else "rock"
        if side != 0:
            self._draw_receding_wall_cell(rect, depth, side, tile_kind)
            return

        wall = self._wall_rect(rect, depth, side)
        if wall.w <= 2 or wall.h <= 2:
            return

        base = TILE_COLOURS.get(tile_kind, TILE_COLOURS["rock"])
        wall_img = None if tile_kind == "water" else self._scene_image_for_kind(tile_kind, "wall", generic=True)
        if wall_img:
            self._blit_scaled(wall_img, wall)
        else:
            top = self._mix(base, (21, 20, 18), 0.35)
            bottom = self._mix(base, (0, 0, 0), 0.22)
            for y in range(wall.h):
                colour = self._mix(top, bottom, y / max(1, wall.h - 1))
                self.pygame.draw.line(self.screen, colour, (wall.x, wall.y + y), (wall.right, wall.y + y))
        if tile_kind == "water":
            for i in range(5):
                yy = wall.y + 18 + i * max(8, wall.h // 7)
                self.pygame.draw.arc(self.screen, (118, 174, 196), self.pygame.Rect(wall.x + 12, yy, wall.w - 24, 18), 0, math.pi, 1)

        veil = self.pygame.Surface((wall.w, wall.h), self.pygame.SRCALPHA)
        veil.fill((0, 0, 0, min(120, 24 + depth * 17 + abs(side) * 15)))
        self.screen.blit(veil, wall)
        self.pygame.draw.rect(self.screen, self._mix(GOLD_DARK, base, 0.32), wall, width=2)
        if side == 0 or depth <= 2:
            self._centered(self.pygame.Rect(wall.x, wall.y + 8, wall.w, 24), TILE_NAMES.get(tile_kind, "blocked"), PAPER, self.tiny)

    def _draw_front_wall_face(self, rect: Any, depth: int, side: int, tile_kind: str) -> None:
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

        base = TILE_COLOURS.get(tile_kind, TILE_COLOURS["rock"])
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
            self._centered(label_rect, TILE_NAMES.get(tile_kind, "blocked"), PAPER, self.tiny)
        self.screen.set_clip(old_clip)

    def _draw_receding_wall_cell(self, rect: Any, depth: int, side: int, tile_kind: str) -> None:
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

        base = TILE_COLOURS.get(tile_kind, TILE_COLOURS["rock"])
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

    def _draw_walkable_feature(self, tile_kind: str, rect: Any, depth: int, side: int) -> None:
        if tile_kind not in {"forest", "ruins", "cave"} or depth > 4:
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

        if tile_kind == "forest":
            trunk = self._mix((75, 50, 27), (0, 0, 0), depth * 0.04)
            leaf = self._mix(TILE_COLOURS["forest"], (0, 0, 0), depth * 0.05)
            for offset in (-0.28, 0.12, 0.36):
                tx = box.centerx + int(box.w * offset)
                self.pygame.draw.line(self.screen, trunk, (tx, box.bottom), (tx + int(10 * scale), box.y + int(28 * scale)), max(1, int(5 * scale)))
                self.pygame.draw.circle(self.screen, leaf, (tx + int(12 * scale), box.y + int(24 * scale)), max(5, int(28 * scale)))
            return

        if tile_kind == "ruins":
            stone = self._mix(TILE_COLOURS["ruins"], (0, 0, 0), 0.14 + depth * 0.04)
            cap = self._mix(PAPER, stone, 0.68)
            for offset in (-0.28, 0.28):
                col = self.pygame.Rect(box.centerx + int(box.w * offset) - max(4, box.w // 10), box.y + box.h // 4, max(8, box.w // 5), box.h * 3 // 4)
                self.pygame.draw.rect(self.screen, stone, col)
                self.pygame.draw.rect(self.screen, cap, self.pygame.Rect(col.x - 3, col.y - 5, col.w + 6, 6))
            return

        arch = self.pygame.Rect(box.x + box.w // 8, box.y + box.h // 5, box.w * 3 // 4, box.h * 4 // 5)
        self.pygame.draw.rect(self.screen, self._mix(TILE_COLOURS["cave"], (0, 0, 0), 0.22), arch, border_radius=max(3, int(10 * scale)))
        self.pygame.draw.rect(self.screen, self._mix(PAPER, TILE_COLOURS["cave"], 0.6), arch, width=max(1, int(2 * scale)), border_radius=max(3, int(10 * scale)))

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
        tile_kind = world.grid.tile_at(pos).kind if world.grid.in_bounds(pos) else "rock"
        wall_img = self.art.scene(tile_kind, "wall") or self.art.scene(tile_kind, "blocker")
        if wall_img:
            self._blit_scaled(wall_img, wall)
        else:
            colour = self._mix(TILE_COLOURS.get(tile_kind, (70, 70, 70)), (21, 18, 17), 0.38)
            self.pygame.draw.rect(self.screen, colour, wall, border_radius=2)
            for x in range(wall.x + 12, wall.right, max(24, int(42 * scale))):
                self.pygame.draw.line(self.screen, self._mix(colour, (180, 170, 135), 0.22), (x, wall.y + 8), (x - 18, wall.bottom - 10), 1)
        self.pygame.draw.rect(self.screen, (163, 140, 82), wall, width=2)
        self._centered(self.pygame.Rect(wall.x, wall.y + 12, wall.w, 24), TILE_NAMES.get(tile_kind, "blocked"), PAPER, self.small)

    def _draw_visible_objects(self, world: WorldState, rect: Any) -> None:
        for depth in range(MAX_VIEW_DEPTH, 0, -1):
            for side in VIEW_SIDES:
                pos = self._relative_position(world.player.position, world.player_facing, depth, side)
                if not self._cell_visible(world, depth, side) or self._sight_blocked(world, pos) or not world.grid.is_walkable(pos):
                    continue
                obj = self._object_at(world, pos)
                if obj:
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
        sprite = self.art.object_sprite(obj.kind)
        if sprite:
            self._draw_sprite(sprite, box)
        else:
            colour = OBJECT_COLOURS.get(obj.kind, (190, 176, 126))
            shadow = box.move(6, 9)
            self.pygame.draw.ellipse(self.screen, (0, 0, 0), self.pygame.Rect(shadow.x, shadow.bottom - 20, shadow.w, 22))
            self.pygame.draw.rect(self.screen, colour, box, border_radius=6)
            self.pygame.draw.rect(self.screen, self._mix(PAPER, colour, 0.6), box, width=2, border_radius=6)
            marker = OBJECT_MARKERS.get(obj.kind, obj.name.upper()[:8])
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
        self._draw_party_stat(rect.x + 8, rect.y + 94, rect.w - 16, "HP", 100.0 - agent.needs.hunger, (190, 56, 52))
        self._draw_party_stat(rect.x + 8, rect.y + 112, rect.w - 16, "TR", agent.social_to_player.trust, (65, 142, 205))

    def _draw_party_stat(self, x: int, y: int, w: int, label: str, value: float, colour: tuple[int, int, int]) -> None:
        self._line(x, y - 2, label, PAPER, self.tiny)
        bar = self.pygame.Rect(x + 28, y + 2, w - 30, 8)
        self.pygame.draw.rect(self.screen, (23, 16, 13), bar)
        fill = self.pygame.Rect(bar.x, bar.y, int(bar.w * max(0, min(100, value)) / 100), bar.h)
        self.pygame.draw.rect(self.screen, colour, fill)
        self.pygame.draw.rect(self.screen, GOLD_DARK, bar, width=1)

    def _draw_bottom_panel(self, world: WorldState, rect: Any) -> None:
        self._ornate_panel(rect, GREEN_PANEL, "Dialogue / Mozok Brain")
        left = self.pygame.Rect(rect.x + 20, rect.y + 34, 420, rect.h - 54)
        mid = self.pygame.Rect(rect.x + 456, rect.y + 34, 246, rect.h - 54)
        right = self.pygame.Rect(rect.x + 718, rect.y + 34, 206, rect.h - 54)

        self._line(left.x, left.y, "Conversation", PAPER, self.label)
        y = left.y + 26
        chat_lines = world.chat_log[-5:] if world.chat_log else []
        if chat_lines:
            for item in chat_lines:
                name = f"{item.speaker_name}:"
                colour = (255, 241, 166) if item.source == "player" else (174, 220, 238)
                self._line(left.x, y, name, colour, self.small)
                for line in self._wrap(item.content, 45, 2):
                    self._line(left.x + 92, y, line, (240, 238, 220), self.small)
                    y += 19
                y += 3
        else:
            for event in world.event_log[-5:]:
                self._line(left.x, y, f"[{event.turn:03d}] {event.content}"[:62], (240, 238, 220), self.small)
                y += 22

        agent = self._focused_agent(world)
        self._line(mid.x, mid.y, "Agent Focus", PAPER, self.label)
        if agent:
            score = f"{agent.brain_focus_score:.2f}" if agent.brain_focus_score else "local"
            self._line(mid.x, mid.y + 28, f"{agent.name} / {score}", (228, 233, 215), self.small)
            y = mid.y + 52
            for line in self._wrap(agent.brain_broadcast or agent.brain_focus, 29, 5):
                self._line(mid.x, y, line, (230, 231, 215), self.small)
                y += 19

        self._line(right.x, right.y, "Memory Notes", PAPER, self.label)
        y = right.y + 28
        for flash in world.brain_flashes[-4:]:
            name = world.agents.get(flash.agent_id).name if world.agents.get(flash.agent_id) else flash.agent_id
            self._line(right.x, y, f"{name}: {flash.title}"[:27], (255, 241, 166), self.tiny)
            y += 16
            for line in self._wrap(flash.content, 25, 2):
                self._line(right.x, y, line, (224, 229, 216), self.tiny)
                y += 15
            y += 4

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

    def _draw_text_chat(self, world: WorldState, text_chat: dict) -> None:
        self._dark_overlay(142)
        target_ids = list(text_chat.get("target_ids", []))
        agents = [world.agents[agent_id] for agent_id in target_ids if agent_id in world.agents]
        names = ", ".join(agent.name for agent in agents) or "nobody"
        mode = str(text_chat.get("mode", "group"))
        title = str(text_chat.get("title") or ("Group Chat" if mode == "group" else "Talk"))
        rect = self.pygame.Rect(226, 74, 828, 500)
        self._ornate_panel(rect, GREEN_PANEL, title)
        lead = f"Facing: {names}" if mode == "direct" else f"Nearby: {names}"
        self._line(rect.x + 26, rect.y + 42, lead, PAPER, self.small)

        x = rect.x + 26
        y = rect.y + 76
        visible_chat = self._chat_lines_for_targets(world, target_ids)
        for line in visible_chat[-9:]:
            speaker_colour = (255, 241, 166) if line.source == "player" else (174, 220, 238)
            self._line(x, y, f"{line.speaker_name}:", speaker_colour, self.small)
            yy = y
            for text in self._wrap(line.content, 78, 3):
                self._line(x + 118, yy, text, (240, 238, 220), self.small)
                yy += 20
            y = max(y + 24, yy + 5)
            if y > rect.y + 360:
                break

        input_rect = self.pygame.Rect(rect.x + 26, rect.bottom - 86, rect.w - 52, 48)
        self.pygame.draw.rect(self.screen, (250, 240, 188), input_rect, border_radius=3)
        self.pygame.draw.rect(self.screen, GOLD_DARK, input_rect, width=2, border_radius=3)
        text = str(text_chat.get("text", ""))
        cursor = "_" if (self.pygame.time.get_ticks() // 450) % 2 == 0 else ""
        self._line(input_rect.x + 14, input_rect.y + 13, (text + cursor)[-88:], INK, self.label)
        hint = "Type message / Enter send / Esc close" if mode == "direct" else "Type message / Enter send to adjacent agents / Esc close"
        self._line(rect.x + 26, rect.bottom - 26, hint, PAPER, self.small)

    def _chat_lines_for_targets(self, world: WorldState, target_ids: list[str]) -> list[Any]:
        target_set = set(target_ids)
        if not target_set:
            return world.chat_log
        return [line for line in world.chat_log if line.speaker_id == "player" or line.speaker_id in target_set]

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
                self.pygame.draw.rect(self.screen, TILE_COLOURS.get(kind, (80, 80, 80)), map_rect)
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

    def _draw_debug(self, world: WorldState) -> None:
        rect = self.pygame.Rect(178, 48, 560, 236)
        self.pygame.draw.rect(self.screen, (0, 0, 0), rect, border_radius=6)
        self.pygame.draw.rect(self.screen, GOLD, rect, width=1, border_radius=6)
        y = rect.y + 14
        self._line(rect.x + 14, y, "DEBUG: world state / MOZOK-facing signals", PAPER, self.small)
        y += 24
        self._line(rect.x + 14, y, f"Player pos: {world.player.position.x},{world.player.position.y} facing={world.player_facing} inv={world.player.inventory}", (230, 230, 230), self.small)
        y += 22
        for agent in world.agents.values():
            text = (
                f"{agent.id}: pos={agent.position.x},{agent.position.y} emotion={agent.emotion} "
                f"h={agent.needs.hunger:.0f} t={agent.needs.thirst:.0f} s={agent.needs.stress:.0f} action={agent.last_action}"
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
        tile_kind = world.grid.tile_at(front).kind if world.grid.in_bounds(front) else "rock"
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
        return world.grid.tile_at(pos).kind == "rock"

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
