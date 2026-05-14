from __future__ import annotations

from dataclasses import dataclass

from mozok_game.engine.models import Position, TileKind


@dataclass(slots=True)
class Tile:
    kind: TileKind
    walkable: bool = True
    label: str = ""


class MapGrid:
    def __init__(self, width: int, height: int, default: TileKind = "grass") -> None:
        self.width = width
        self.height = height
        self.tiles: list[list[Tile]] = [[Tile(default, True) for _ in range(width)] for _ in range(height)]

    def in_bounds(self, pos: Position) -> bool:
        return 0 <= pos.x < self.width and 0 <= pos.y < self.height

    def tile_at(self, pos: Position) -> Tile:
        return self.tiles[pos.y][pos.x]

    def set_tile(self, x: int, y: int, kind: TileKind, walkable: bool = True, label: str = "") -> None:
        self.tiles[y][x] = Tile(kind=kind, walkable=walkable, label=label)

    def is_walkable(self, pos: Position) -> bool:
        if not self.in_bounds(pos):
            return False
        return self.tile_at(pos).walkable

    def neighbours(self, pos: Position) -> list[Position]:
        candidates = [Position(pos.x + 1, pos.y), Position(pos.x - 1, pos.y), Position(pos.x, pos.y + 1), Position(pos.x, pos.y - 1)]
        return [p for p in candidates if self.is_walkable(p)]

    @classmethod
    def from_ascii(cls, rows: list[str]) -> "MapGrid":
        legend: dict[str, tuple[TileKind, bool]] = {
            ".": ("grass", True),
            ",": ("sand", True),
            "T": ("forest", True),
            "~": ("water", False),
            "#": ("rock", False),
            "C": ("camp", True),
            "V": ("cave", True),
            "R": ("ruins", True),
        }
        height = len(rows)
        width = max(len(row) for row in rows)
        grid = cls(width, height)
        for y, row in enumerate(rows):
            for x, char in enumerate(row.ljust(width, ".")):
                kind, walkable = legend.get(char, ("grass", True))
                grid.set_tile(x, y, kind, walkable)
        return grid
