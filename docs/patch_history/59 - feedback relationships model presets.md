# 59 - Feedback, Relationships, And Model Presets

## Summary

- Added visible player action feedback for object interactions. Player interactions now add an `Action` line to the conversation feed, so inspect/open/pry results are no longer hidden behind event logs.
- Added state-aware interaction messages through `message_by_state`, used by the locked supply box so inspecting it before and after prying gives different feedback.
- Added ergonomic LLM model presets in the in-game model role panel:
  - `A` applies the selected model to all roles.
  - `P` applies it to powerful roles: chat, scene, reasoning.
  - `H` applies it to helper roles: semantic, fast, summarizer, maintenance.
- Added a dialogue reaction layer that updates agent emotion and player relationship deltas after each player line.
- Added social-effect feedback in the chat window showing trust/fear/affinity/resentment changes and current emotion.
- Added an agent relationship model and a bottom-panel `Relations` tab showing each agent toward the player plus agent-to-agent relationship tracks.

## Verification

- `python -m compileall -q mozok_game mozok`
- JSON data load smoke check for `mozok_game/data/**/*.json`
- Direct local smoke runner over `mozok_game.tests.test_engine` and `mozok_game.tests.test_director`: `63 passed, 0 failed`
