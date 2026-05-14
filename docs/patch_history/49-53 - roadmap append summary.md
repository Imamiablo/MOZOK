# 49-53 - Roadmap append summary

## 49 — Mini Brain UI MVP - DONE

- Added a tiny browser UI at `/ui`.
- Added lightweight pages for Scenario Studio and Visual Knowledge Graph.
- The UI is intentionally small and links back to Swagger for real operations.

## 50 — Scenario Studio MVP - DONE

- Added draft-to-brain-pack schemas and service.
- Added `/scenario-studio/build` and `/scenario-studio/save`.
- Supports agents, lore, goals, skills, entity states, memories, knowledge relations, and auto-linking.

## 51 — Runtime Tick V2 - DONE

- Added batch runtime tick endpoint for multiple agents.
- Added per-agent tick history endpoint.
- Tick history stores selected action, cognitive winner, proposal count, and metadata.

## 52 — Visual Knowledge Graph MVP - DONE

- Added `/agents/{agent_id}/knowledge-graph/visual`.
- Exports graph nodes/edges as JSON, Cytoscape-style elements, and Mermaid text.

## 53 — Showcase Demo Scenario Pack - DONE

- Added `showcase_old_well_brain_pack.json`.
- Added `showcase_old_well_eval_pack.json`.
- Demo covers lore visibility, secrets, goals, skills, relations, memories, and evaluation expectations.
