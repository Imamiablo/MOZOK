from __future__ import annotations

from dataclasses import dataclass

from mozok_game.engine.models import Position, TileKind


@dataclass(slots=True)
class Tile:
    kind: TileKind
    walkable: bool = True
    label: str = ""
    tags: list[str] | None = None
    movement_cost: float = 1.0


class MapGrid:
    def __init__(self, width: int, height: int, default: TileKind = "floor", tile_defs: dict[str, dict] | None = None) -> None:
        self.width = width
        self.height = height
        self.tile_defs = dict(tile_defs or {})
        default_def = self.tile_defs.get(default, {})
        self.tiles: list[list[Tile]] = [
            [
                Tile(
                    default,
                    bool(default_def.get("walkable", True)),
                    str(default_def.get("label") or ""),
                    list(default_def.get("tags") or []),
                    float(default_def.get("movement_cost", 1.0)),
                )
                for _ in range(width)
            ]
            for _ in range(height)
        ]

    def in_bounds(self, pos: Position) -> bool:
        return 0 <= pos.x < self.width and 0 <= pos.y < self.height

    def tile_at(self, pos: Position) -> Tile:
        return self.tiles[pos.y][pos.x]

    def set_tile(self, x: int, y: int, kind: TileKind, walkable: bool | None = None, label: str = "") -> None:
        tile_def = self.tile_defs.get(kind, {})
        final_walkable = bool(tile_def.get("walkable", True)) if walkable is None else bool(walkable)
        self.tiles[y][x] = Tile(
            kind=kind,
            walkable=final_walkable,
            label=label or str(tile_def.get("label") or ""),
            tags=list(tile_def.get("tags") or []),
            movement_cost=float(tile_def.get("movement_cost", 1.0)),
        )

    def is_walkable(self, pos: Position) -> bool:
        if not self.in_bounds(pos):
            return False
        return self.tile_at(pos).walkable

    def neighbours(self, pos: Position) -> list[Position]:
        candidates = [Position(pos.x + 1, pos.y), Position(pos.x - 1, pos.y), Position(pos.x, pos.y + 1), Position(pos.x, pos.y - 1)]
        return [p for p in candidates if self.is_walkable(p)]

    @classmethod
    def from_ascii(cls, rows: list[str], legend: dict[str, object] | None = None, tile_defs: dict[str, dict] | None = None) -> "MapGrid":
        default_legend: dict[str, tuple[TileKind, bool]] = {
            ".": ("floor", True),
            "#": ("wall", False),
            "~": ("water", False),
            "S": ("floor", True),
            "@": ("floor", True),
        }
        parsed_legend = _parse_legend(legend, default_legend)
        height = len(rows)
        width = max(len(row) for row in rows)
        grid = cls(width, height, tile_defs=tile_defs)
        for y, row in enumerate(rows):
            for x, char in enumerate(row.ljust(width, ".")):
                kind, walkable = parsed_legend.get(char, ("floor", True))
                grid.set_tile(x, y, kind, walkable)
        return grid


def _parse_legend(raw: dict[str, object] | None, default: dict[str, tuple[TileKind, bool]]) -> dict[str, tuple[TileKind, bool]]:
    legend = dict(default)
    for char, value in dict(raw or {}).items():
        key = str(char)[:1]
        if isinstance(value, dict):
            legend[key] = (str(value.get("kind") or value.get("tile") or "floor"), bool(value.get("walkable", True)))
        elif isinstance(value, (list, tuple)) and value:
            legend[key] = (str(value[0]), bool(value[1]) if len(value) > 1 else True)
        else:
            legend[key] = (str(value), True)
    return legend
