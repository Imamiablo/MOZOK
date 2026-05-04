# Patch 11 - Context token budget MVP

Adds a lightweight prompt/context budget layer.

## What this does

- Adds `mozok/context/token_budget.py`.
- Estimates prompt tokens with a cheap character-based heuristic (`len(text) / 4`).
- Trims selected context only when the prompt is over budget.
- Trims in this order:
  1. raw memories
  2. episodic memories
  3. semantic memories
  4. oldest short-term messages
  5. core/profile memories only if `allow_core_trimming=true`
- Adds `context_budget` debug output to `/debug/context` and `/chat` responses.
- Keeps `/debug/context` read-only for memory `access_count` when the read-only patch is present.

## What this does not do yet

This is not a production-grade model tokenizer.
Future versions should add:

- model-specific tokenization;
- per-section budgets;
- summarization/compression when over budget;
- smarter score-aware reranking before trimming;
- tests for trimming and budget reports;
- config/profile presets per backend agent.
