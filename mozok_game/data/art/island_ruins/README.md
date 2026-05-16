# Island Ruins Art Pack

Drop PNG assets here to replace the procedural fallback art in the first-person dungeon renderer.

The game will keep running if any file is missing.

The included PNGs are generated local demo art. Regenerate them with:

```powershell
.\.venv\Scripts\python.exe scripts\generate_island_ruins_art.py
```

The generated `preview.png` is only a quick composition preview; the game renderer composes the same pack dynamically from the current grid scene.

## Scene Layers

Optional full-scene and texture layers:

```text
scene/backdrop.png
scene/floor.png
scene/wall.png
scene/blocker.png
```

Tile-specific variants override generic scene layers:

```text
tiles/cave/backdrop.png
tiles/cave/floor.png
tiles/cave/wall.png
tiles/ruins/backdrop.png
tiles/ruins/floor.png
tiles/ruins/wall.png
tiles/grass/backdrop.png
```

Useful canvas sizes:

- `backdrop.png`: 944x436 or larger, no transparency required.
- `floor.png` / `wall.png`: tileable or texture-like PNG, any medium/large size.

## Objects

Transparent PNG billboards:

```text
objects/campfire.png
objects/food_crate.png
objects/water_source.png
objects/cave_entrance.png
objects/broken_radio.png
objects/shelter.png
```

Recommended size: 256x256 or 512x512 transparent PNG.

## Characters

Transparent PNG billboards:

```text
characters/alice/neutral.png
characters/alice/curious.png
characters/boris/suspicious.png
characters/mira/afraid.png
```

Fallback order:

1. `characters/<agent_id>/<emotion>.png`
2. `characters/<agent_id>/neutral.png`
3. `characters/<agent_id>.png`
4. Existing `data/avatars/<agent>/<emotion>.png`

Recommended size: 512x768 or 768x1024 transparent PNG.

## Style Notes

For a Class-of-Heroes-like look, use:

- painted stone corridor backgrounds,
- strong golden UI frames,
- transparent character sprites placed as billboards,
- brighter portraits for party cards,
- full-body enemies/NPCs centered in the corridor.
