# 56 - Scenario Pack Loader and Template Foundation

## Summary

This pass moves the game sandbox closer to an editor/generator-ready shape.

The island demo is no longer the only canonical data shape. The loader can still read the older monolithic scenario JSON, but the preferred path now assembles a world from pack refs:

- `map_ref`
- `object_pack_refs`
- `character_refs`
- `item_pack_refs`
- `dialogue_pack_refs`
- `director_moment_pack_refs`
- `storylet_pack_refs`
- `drama_atom_pack_refs`

## Changes

- Added map/object/character/storylet/drama/dialogue/director pack loading in `WorldState`.
- Split the island demo map into `data/maps/island_camp_01.json`.
- Split island world objects into `data/objects/island_survival_objects.json` with reusable templates and placed instances.
- Split dialogue templates into `data/dialogue/island_survival_dialogue.json`.
- Split director moments into `data/director_moments/island_survival_moments.json`.
- Kept old monolithic scenario support for compatibility.
- Removed the static island object alias table as runtime source of truth; aliases now come from live world object data.
- Added a player interaction menu for objects with multiple interactions.
- Expanded the storylet executor with basic trigger tags/event requirements, cooldown/max occurrence metadata, object state, claim, flash, and need/social effects.
- Added `SceneContext` as a first structured contract for future LLM scene weaving.
- Added scenario-level pressure tag/event delta overrides, so setting-specific tags such as cave/radio pressure can live in scenario data instead of the core pressure table.
- Added tests for pack loading, object templates, scene context, dynamic aliases, and generic director behaviour.

## Verification

- `python -m compileall -q mozok_game` passed with the bundled Python runtime.
- Direct no-pytest smoke runner over no-argument game tests passed with a local `requests` stub.
- Full pytest was not available in this runtime because the bundled Python does not include `pytest`.
