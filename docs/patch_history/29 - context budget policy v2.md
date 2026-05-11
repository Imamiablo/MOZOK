# 30 - Context Budget Policy V2

## Summary

This patch upgrades context-budget handling from one global last-resort trimmer into a more transparent V2 policy layer.

## Implemented

- Model-aware approximate token estimation through `token_estimation_model`.
- Optional explicit per-section budgets through `section_budget_tokens`.
- Section token reports in the context budget debug payload.
- Request-local compression of oversized budgeted sections before dropping items.
- Deterministic short-term summarisation when old short-term messages would overflow the prompt.
- Budget-aware one-hop knowledge-relation expansion cap.
- Backwards-compatible legacy total-budget trimming when explicit section budgets are not supplied.

## Changed files

- `mozok/context/token_budget.py`
- `mozok/context/context_builder.py`
- `mozok/schemas/chat.py`
- `mozok/schemas/context.py`
- `mozok/api/main.py`
- `mozok/core/bot_core.py`
- `tests/unit/test_context_budget_policy_v2.py`
- `ROADMAP.md`

## Behaviour notes

`section_budget_tokens` is intentionally explicit. If a caller does not provide explicit per-section caps, Mozok still reports section estimates but keeps legacy total-budget trimming behaviour. This avoids surprising prompt changes for existing `/chat` and `/debug/context` users.

Compression is request-local: it changes only the prompt text for the current context package. It does not mutate PostgreSQL records, FAISS data, or the stored memory content.

Short-term summarisation is deterministic and local. It does not call the LLM. Older short-term turns are collapsed into one compact `system` working-memory note while the newest turns remain as individual messages.

Budget-aware graph expansion caps one-hop relation fan-out before relation records are added to the prompt. The cap is based on the `knowledge_relations` section budget and the number of explicitly selected relations.

## Tests

Added V2 coverage for:

- model-aware token estimation;
- explicit section-budget compression;
- short-term summarisation;
- budget-aware relation expansion cap.

Full test run:

```text
129 passed, 3 skipped, 7 warnings
```

The 3 skipped tests are HTTP smoke tests that require a live local Mozok API.
