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
- asset-driven Class-of-Heroes-style 2.5D renderer
- dialogue topic menu
- free-text group chat through MOZOK `/chat`
- memory flash feed
- cognitive-field/intent panel
- data-driven pressure/storylet moments for cave, radio, food, weather, and social stress
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

## Art packs

The renderer uses a 2.5D dungeon-crawler layout with side party panels, a central pseudo-3D scene, and a bottom dialogue/brain panel. It automatically uses PNG assets from:

```text
mozok_game/data/art/island_ruins/
```

Useful drop-in paths:

```text
scene/backdrop.png
scene/floor.png
scene/wall.png
objects/food_crate.png
objects/campfire.png
objects/cave_entrance.png
characters/alice/curious.png
characters/boris/suspicious.png
characters/mira/afraid.png
```

Tile-specific floor and wall art can override the generic scene art:

```text
tiles/ruins/wall.png
tiles/grass/floor.png
```

Missing assets are fine; the game draws a procedural map-aware 2.5D view.

This repo also includes a local generator for the current demo pack:

```powershell
.\.venv\Scripts\python.exe scripts\generate_island_ruins_art.py
```

It creates scene textures, object sprites, character billboard sprites, and `preview.png`.

## Controls

- `W` / Up: step forward
- `S` / Down: step backward
- `A` / Left: turn left
- `D` / Right: turn right
- `E`: interact with the object ahead, or open direct free-text chat with the agent on the tile ahead
- `T`: open free-text group chat with all agents on neighbouring tiles
- `I`: open the selected/front/nearby agent dossier
- `G`: give the first item in your inventory to the agent directly ahead
- `R`: request/take the first item from the agent directly ahead
- `Enter`: send the current direct or group chat message
- Up/Down while chatting: scroll conversation history
- `Space`: wait / end turn
- `Tab`: toggle debug overlay
- `Esc`: quit

## Agent Speech Actions

Direct or group chat is no longer only dialogue text. Simple player speech can now become a simulation command:

- "follow me" / "stay close" can create a follow commitment
- "stop following" / "wait here" clears that commitment
- "go to the campfire/water/cave/radio/food" can create a task
- hostile phrases make the agent react socially instead of starting silent combat

Agents can accept or refuse based on trust, fear, stress, resentment, personality bias, and perceived danger. The world still validates movement and tasks.

In MOZOK API mode, player text first goes through an LLM semantic parser that returns structured speech acts and unverified claims. That means slang, paraphrases, lies, manipulation, threats, and requests should be interpreted by meaning instead of by fixed keyword lists. Offline mode keeps a tiny fallback parser only so the demo remains usable without the backend.

## Agent Deliberation Layer

Each agent now builds a short list of possible actions before acting:

- satisfy an urgent body need by moving to a tagged world object
- verify an unconfirmed claim from the player
- talk to the player when social pressure is high
- talk to another nearby agent to coordinate or challenge a concern
- give an item to another agent when hunger, wounds, or trust make it useful
- use carried inventory items such as rations or medkits
- use an item's capability on an existing world object, such as any data-declared `pry`, `anchor`, `test`, `repair`, or `inspect` target
- investigate mystery objects when curiosity beats fear
- wait when nothing else is worth doing

The game engine still owns movement and world validation. MOZOK or the offline brain chooses from these affordances, then the tick scheduler applies the result. Press `I` in-game to open an agent dossier with their current goal, traits, values, fears, active target object or agent, commitment, deliberation summary, item capabilities, remembered claims, memory snippets, and recent dialogue.

## Simulation Core Pass

The sandbox now has the first version of the generic simulation architecture:

- character cards: traits, values, fears, skills, and personality are loaded from scenario data
- data-driven item capability layer: `data/items/items.json` defines tags, capabilities, and properties
- data-driven target effects: scenario objects can declare `capability_accepts` and `capability_effects`; the capability executor no longer has island-specific branches for cave/lockbox/berries
- commitment objects: accepted player requests become active task records with type, target, constraints, expiry, and history; old follow/target fields are now only derived UI/cache fields
- pressure field: events move axes such as scarcity, danger, mystery, instability, authority, dependency, and exhaustion
- structured event ledger: world events carry actor, target, item, location, witnesses, visibility, reliability, truth status, and idempotency key
- storylet deck: `data/storylets/storylets.json` defines condition-driven events such as cold rain
- drama atoms and impulses: `data/drama_atoms/core_atoms.json` maps pressures + traits + recent events into candidate actions
- authoritative state export: physical state stays owned by the game and is sent to MOZOK as structured context

## Items And World Pressure

The island now includes a first item/pressure pass:

- poisonous berries
- knife
- rope
- medkit
- torn journal page
- locked supply box
- pressure-driven cold rain storylet
- wounded agent state

Items can sit in the player inventory or an agent inventory. The player can pick up objects with `E`, give with `G`, and request with `R`. Agents can also pick up, use, and share items through their autonomous deliberation loop. New scenario items should be described with tags, capabilities, and properties rather than one-off scripted pairings.

Objects can accept capabilities directly in scenario data:

```json
{
  "kind": "custom_anchor",
  "capability_accepts": ["anchor"],
  "capability_effects": {
    "anchor": {
      "target_state": { "secured": true },
      "consume_item": true
    }
  }
}
```

## What to show in a demo

1. Turn toward the camp and step around in first-person grid view.
2. Move near the food crate and interact.
3. Move near the spring and drink.
4. Face Alice, Boris, or Mira, press `E`, and type a direct question.
5. Wait several turns.
6. Watch agents move, become hungry/thirsty/tired/stressed, and change avatar emotion.
7. Point at each agent's visible intent/rationale panel.
8. Stand next to one or more agents, press `T`, type a question, and send it to the whole nearby group.
9. In MOZOK API mode, each adjacent agent answers through `/chat` using its own memories, goals, entity state, and cognitive field.
10. Keep the chat window open and show that replies stay readable instead of disappearing into the event feed.
11. Inspect the cave, radio, or food crate and point at memory flashes.
12. Open the event log/debug overlay and explain that these events are what MOZOK can consume.

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
