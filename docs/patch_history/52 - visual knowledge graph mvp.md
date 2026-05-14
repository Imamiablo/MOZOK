# 52 - Visual Knowledge Graph MVP

Added a UI-friendly graph export layer over existing KnowledgeRelation edges.

## Added

- `mozok/visual_graph/schemas.py`
- `mozok/visual_graph/service.py`
- `POST /agents/{agent_id}/knowledge-graph/visual`

## Output formats

- Normal JSON nodes/edges.
- Cytoscape-style export.
- Mermaid graph text.

This makes the relation graph easier to show in demos and future editors.
