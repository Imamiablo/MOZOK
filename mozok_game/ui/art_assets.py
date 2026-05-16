from __future__ import annotations

from pathlib import Path
from typing import Any


class ArtAssets:
    """Lazy PNG loader for the 2.5D dungeon-crawler renderer.

    The renderer is deliberately asset-driven: drop transparent PNGs into
    data/art/<pack>/... and they replace the procedural fallback art.
    """

    def __init__(self, pygame: Any, base_dir: Path, pack_name: str = "island_ruins") -> None:
        self.pygame = pygame
        self.base_dir = base_dir
        self.pack_name = pack_name
        self.root = base_dir / "data" / "art" / pack_name
        self.cache: dict[Path, Any | None] = {}

    def image(self, *parts: str) -> Any | None:
        path = self.root.joinpath(*parts)
        if path in self.cache:
            return self.cache[path]
        if not path.exists():
            self.cache[path] = None
            return None
        image = self.pygame.image.load(str(path)).convert_alpha()
        self.cache[path] = image
        return image

    def first(self, candidates: list[tuple[str, ...]]) -> Any | None:
        for candidate in candidates:
            image = self.image(*candidate)
            if image is not None:
                return image
        return None

    def scene(self, tile_kind: str, layer: str) -> Any | None:
        return self.first(
            [
                ("tiles", tile_kind, f"{layer}.png"),
                ("scene", f"{tile_kind}_{layer}.png"),
                ("scene", f"{layer}.png"),
            ]
        )

    def object_sprite(self, kind: str) -> Any | None:
        return self.first(
            [
                ("objects", f"{kind}.png"),
                ("sprites", "objects", f"{kind}.png"),
            ]
        )

    def character_sprite(self, agent_id: str, emotion: str, avatar_folder: str) -> Any | None:
        return self.first(
            [
                ("characters", agent_id, f"{emotion}.png"),
                ("characters", agent_id, "neutral.png"),
                ("characters", f"{agent_id}.png"),
                ("characters", avatar_folder, f"{emotion}.png"),
                ("characters", avatar_folder, "neutral.png"),
                ("characters", f"{avatar_folder}.png"),
            ]
        )
