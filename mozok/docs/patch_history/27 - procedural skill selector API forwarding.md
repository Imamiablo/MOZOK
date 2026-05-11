# 27 - Procedural skill selector API forwarding

## Summary

This patch connects the procedural skill selector controls that were already present in the public request schemas to the live `/chat` and `/debug/context` routes.

Before this patch, Swagger exposed the selector fields, but the API layer did not pass them through to `BotCore.chat()` or `ContextBuilder.build()`. As a result, clients could set the fields in requests and still get priority-based procedural skill selection.

## Changed files

- `mozok/api/main.py`
- `tests/unit/test_procedural_skill_selector_api_forwarding.py`
- `requirements.txt`
- `requirements-dev.txt`

## Behaviour

The following request fields are now forwarded by both `/chat` and `/debug/context`:

- `select_relevant_procedural_skills`
- `procedural_skill_min_score`
- `procedural_skill_fallback_to_priority`

This means the API can now use the deterministic V2 procedural skill selector from normal chat/debug requests, not only from lower-level tests or direct service calls.

## Tests

Added API forwarding tests for:

- `/chat`
- `/debug/context`

The tests use lightweight monkeypatching, so they do not call PostgreSQL, FAISS, or Ollama.

## Notes

The requirements files were added as a project dependency snapshot so a fresh environment has a clear install path.
