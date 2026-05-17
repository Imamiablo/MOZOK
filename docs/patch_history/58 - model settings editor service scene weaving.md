# 58 - Model Settings, Editor Service, Scene Weaving

## Summary

- Added in-game LLM model role settings overlay.
- Added editor-service CRUD helpers for scenario/object/character pack workflows.
- Moved belief appraisal rules into a data pack.
- Started routing social dialogue and structured speech decisions through LLM-backed SceneProposal/voice flows when API mode is enabled.
- Reduced renderer island fallback vocabulary so map/object render metadata is the primary source of visual meaning.

## Gameplay / UI

- Press `M` in the sandbox to open model role settings.
- Use Up/Down to select a role, Enter to edit, Tab to cycle known models, Delete to clear, `Ctrl+S` to save, `R` to refresh local Ollama models, and Esc to close.
- Saved role settings are stored in `mozok_game/user_model_settings.json` unless `MOZOK_GAME_MODEL_SETTINGS_PATH` is set.

## Engine

- `mozok_game/engine/editor_service.py` adds helpers for:
  - create/duplicate scenario
  - add/move/remove object instance
  - edit character overrides
  - validate all packs
  - validate generated scenario drafts through pack validation and preview world load
- `mozok_game/data/appraisals/core_appraisals.json` defines data-driven appraisal rules.
- `WorldState` now loads `appraisal_pack_refs`.
- Storylet director has basic chaos-aware pacing and a recovery beat.
- Social director accepts an optional scene weaver callback and falls back to dialogue pack templates.
- Speech decision fallback lines are now dialogue-pack driven; API mode can voice structured decisions through `voice_agent_decision`.

## Verification

- `python -m compileall -q mozok_game mozok`
- JSON load for `mozok_game/data/**/*.json`
- Direct game smoke tests: 59 passed
- `git diff --check` clean apart from line-ending warnings
