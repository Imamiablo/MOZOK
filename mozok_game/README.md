# MOZOK: Island Sandbox Prototype

A small playable first-person grid social survival prototype for demonstrating MOZOK as an AI brain backend.

This prototype is intentionally compact:

- first-person grid movement
- three agents with needs and emotions
- interactable world objects
- turn/tick loop
- event log
- dialogue panel
- avatar-expression panel
- tactical minimap
- dialogue topic menu
- memory flash feed
- cognitive-field/intent panel
- scripted cave, radio, and food-supply moments
- offline fallback brain so the demo works even without MOZOK running
- optional MOZOK HTTP bridge for later integration

## Quick start

From the project root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-game.txt
.\.venv\Scripts\python.exe mozok_game\main.py
```

Or run:

```powershell
run_mozok_island_demo.bat
```

For the full MOZOK API bridge demo, run this from the project root:

```powershell
run_mozok_island_full.bat
```

That launcher starts PostgreSQL, initialises the Mozok database, imports the island brain pack, starts the API on `http://127.0.0.1:8001`, and opens the game with API mode enabled.

## Controls

- `W` / Up: step forward
- `S` / Down: step backward
- `A` / Left: turn left
- `D` / Right: turn right
- `E`: interact with object ahead, or open dialogue with agent ahead
- `T`: open dialogue menu with nearby agent
- `1` / `2` / `3`: choose dialogue topic
- `Space`: wait / end turn
- `Tab`: toggle debug overlay
- `Esc`: quit

## What to show in a demo

1. Turn toward the camp and step around in first-person grid view.
2. Move near the food crate and interact.
3. Move near the spring and drink.
4. Talk to Alice, Boris, or Mira.
5. Wait several turns.
6. Watch agents move, become hungry/thirsty/tired/stressed, and change avatar emotion.
7. Point at each agent's visible intent/rationale panel.
8. Choose a dialogue topic and show that the conversation can surface memory, intent, trust, fear, or suspicion.
9. Inspect the cave, radio, or food crate and point at memory flashes.
10. Open the event log/debug overlay and explain that these events are what MOZOK can consume.

## MOZOK integration mode

By default the prototype uses `OfflineMozokBrain`, so it is playable immediately.

To use a running MOZOK server later, set:

```powershell
$env:MOZOK_GAME_USE_API="1"
$env:MOZOK_API_BASE_URL="http://127.0.0.1:8001"
.\.venv\Scripts\python.exe mozok_game\main.py
```

The bridge is deliberately conservative. The game engine still validates and applies actions. MOZOK only proposes intent/actions.

## Design principle

The game owns the body and world rules.

MOZOK owns memory, personality, interpretation, intention, reflection, and social meaning.

That means the agent may *want* to move to water, confront the player, or inspect the cave — but the game validates whether that is actually possible.

## Files

- `engine/` — deterministic game simulation, needs, ticks, interactions
- `mozok_client/` — offline brain and optional HTTP client
- `ui/` — Pygame renderer and input handling
- `data/` — map, agents, objects, scenario
- `tests/` — unit tests that do not require Pygame

## Notes

This is a vertical-slice prototype, not a finished game. It is designed to be fun to poke, easy to extend, and useful as a living testbed for MOZOK.
