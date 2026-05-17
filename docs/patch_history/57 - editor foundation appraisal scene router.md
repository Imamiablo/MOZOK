# 57 - Editor Foundation, Appraisal, Scene Contract, Model Router

## Summary

- Added editor-facing pack validation and helper functions for scenarios, maps, object packs, character cards, and storylet packs.
- Made the map fallback legend generic (`floor`, `wall`, `water`) so island tile symbols live in the island map pack instead of the engine core.
- Added agent appraisals: witnessed beliefs now become scored concerns that can boost matching drama impulses.
- Added a structured scene proposal contract and validator for future LLM scene weaving.
- Improved storylet director selection from first-eligible to weighted/scored eligible selection with cooldown groups and pacing flags.
- Expanded storylet requirements/effects for belief gates, claim gates, object state gates, inventory gates, goals, commitments, choice offers, location access, and relationship deltas.
- Moved agent-to-agent social lines through the dialogue pack instead of fixed Python strings.
- Added backend LLM model routing by exact model or role (`chat`, `scene`, `semantic`, `fast`, `reasoning`, `summarizer`, `maintenance`).

## Notes

- The game bridge now sends `llm_model_role` hints to MOZOK for tick/chat/semantic-parser calls.
- The default island demo remains a scenario pack; the new validation helpers are meant as the first service layer for a future scenario editor.
