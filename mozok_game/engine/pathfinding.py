from __future__ import annotations

from collections import deque

from mozok_game.engine.map_grid import MapGrid
from mozok_game.engine.models import Position


def next_step_towards(grid: MapGrid, start: Position, target: Position, blocked: set[tuple[int, int]] | None = None) -> Position | None:
    blocked = blocked or set()
    if start.x == target.x and start.y == target.y:
        return None
    queue: deque[Position] = deque([start])
    came_from: dict[tuple[int, int], tuple[int, int] | None] = {(start.x, start.y): None}
    while queue:
        current = queue.popleft()
        if current.x == target.x and current.y == target.y:
            break
        for neighbour in grid.neighbours(current):
            key = (neighbour.x, neighbour.y)
            if key in came_from or key in blocked:
                continue
            came_from[key] = (current.x, current.y)
            queue.append(neighbour)
    target_key = (target.x, target.y)
    if target_key not in came_from:
        return None
    current = target_key
    while came_from[current] != (start.x, start.y):
        if came_from[current] is None:
            return None
        current = came_from[current]  # type: ignore[assignment]
    return Position(*current)
