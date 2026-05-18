# 60 - LLM performance budget

## Goal

Reduce sandbox lag in MOZOK API mode without turning NPCs into dumb scripted actors.

## Changes

- Added `mozok_game.engine.performance` with runtime knobs for:
  - max LLM agent ticks per turn
  - per-agent LLM tick cooldown
  - group-chat LLM reply budget
  - social-scene LLM interval
  - decision-voice policy
  - compact payload limits
- `MozokHttpClient.decide()` now uses the local deterministic planner for low-salience ticks once the per-turn LLM budget is spent.
- LLM tick calls still prioritise salient situations, but simple proximity no longer bypasses cooldown. Truly critical events still cut through: active commitments, urgent needs, high social pressure, or recent high-salience witnessed events.
- Semantic parsing is cached per turn/message/world-object signature, so one group chat message is parsed once instead of once per nearby agent.
- Group chat now limits full LLM replies and voiced decision rewrites by default. Non-primary nearby agents still update emotion/social state and respond through the local fallback.
- Chat/tick/scene payloads are compacted to nearby/high-priority objects, recent events, and shorter scene context.
- `.env.example` documents the performance controls.

## Verification

- `compileall` passed for `mozok_game`.
- Direct local runner passed `66` game/director tests.
