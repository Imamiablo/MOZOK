# 61 - Async LLM jobs

## Goal

Keep the pygame sandbox responsive while MOZOK/LLM calls are still running.

## Changes

- Added async LLM settings:
  - `MOZOK_GAME_ASYNC_LLM`
  - `MOZOK_GAME_ASYNC_WORKERS`
  - `MOZOK_GAME_ASYNC_PENDING_LIMIT`
  - `MOZOK_GAME_ASYNC_DECISION_TTL_TURNS`
- Added `AsyncMozokBrain`, a non-blocking wrapper around `MozokHttpClient`.
- Agent autonomy now returns local behaviour immediately, queues the expensive LLM decision in the background, then uses the ready result on a later tick if it is still fresh.
- Social scene weaving is skipped in async mode instead of blocking the render loop.
- Text chat now queues model replies in the background. The UI shows a placeholder line and replaces it when the model response is ready.
- Chat result application stays on the pygame thread, so claims, commitments, relationship changes, and grounded dialogue validation remain safe.

## Verification

- `compileall` passed for `mozok_game`.
- Direct local runner passed `68` game/director tests.

