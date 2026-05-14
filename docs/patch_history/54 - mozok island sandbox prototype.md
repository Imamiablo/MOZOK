# 54 - MOZOK Island Sandbox Prototype

Added a standalone playable prototype client under `mozok_game/`.

## Added

- Pygame-based 2D grid sandbox.
- Turn-based player movement and wait/action loop.
- Three social-survival agents: Alice, Boris, and Mira.
- Needs model: hunger, thirst, fatigue, stress, social need, curiosity.
- Emotion model with visible avatar-expression cards.
- Interactable objects: campfire, food crate, shelter, spring, broken radio, cave entrance.
- Offline deterministic brain fallback so the demo runs without a MOZOK server.
- Optional HTTP bridge for future MOZOK runtime-tick integration.
- Event log and debug overlay.
- Unit tests for loading, interaction, pathfinding, and agent ticks.

## Intent

This is a living demonstration layer for MOZOK: the game owns world rules and validation, while MOZOK can own memory, interpretation, intention, action planning, reflection, and social meaning.

## Manual check

Run:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-game.txt
.\.venv\Scripts\python.exe mozok_game\main.py
```

Then move around, interact with the food crate/spring/cave, talk to agents, wait several turns, and press `Tab` for the debug overlay.
