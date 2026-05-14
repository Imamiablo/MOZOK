from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from mozok.knowledge_relations.service import KnowledgeRelationService
from mozok.schemas.knowledge_relations import KnowledgeRelationRead
from mozok.visual_graph.schemas import (
    VisualKnowledgeGraphEdge,
    VisualKnowledgeGraphNode,
    VisualKnowledgeGraphRequest,
    VisualKnowledgeGraphResponse,
)


def _node_key(node_type: str, node_id: str) -> str:
    return f"{node_type}:{node_id}"


def _label(node_type: str, node_id: str, max_chars: int) -> str:
    text = f"{node_type}: {node_id}"
    return text if len(text) <= max_chars else text[: max_chars - 3] + "..."


def _safe_mermaid_id(value: str) -> str:
    return "n_" + "".join(ch if ch.isalnum() else "_" for ch in value)[:80]


class VisualKnowledgeGraphService:
    """Converts KnowledgeRelation edges into UI-friendly graph exports."""

    def __init__(self, db: Session):
        self.db = db

    def build(self, agent_id: str, request: VisualKnowledgeGraphRequest) -> VisualKnowledgeGraphResponse:
        records = KnowledgeRelationService(self.db).list_relations(
            agent_id=agent_id,
            world_id=request.world_id,
            include_inactive=request.include_inactive,
            limit=request.limit,
        )
        relations = [KnowledgeRelationRead.from_record(record) for record in records]
        if request.relation_types:
            allowed = {item.strip() for item in request.relation_types}
            relations = [item for item in relations if item.relation_type in allowed]
        relations = [item for item in relations if item.strength >= request.min_strength and item.confidence >= request.min_confidence]

        nodes_by_id: dict[str, VisualKnowledgeGraphNode] = {}
        edges: list[VisualKnowledgeGraphEdge] = []
        for relation in relations[: request.limit]:
            source = _node_key(relation.source_type, relation.source_id)
            target = _node_key(relation.target_type, relation.target_id)
            nodes_by_id.setdefault(
                source,
                VisualKnowledgeGraphNode(
                    id=source,
                    node_type=relation.source_type,
                    node_id=relation.source_id,
                    label=_label(relation.source_type, relation.source_id, request.node_label_max_chars),
                    group=relation.source_type,
                    score=0.0,
                ),
            )
            nodes_by_id.setdefault(
                target,
                VisualKnowledgeGraphNode(
                    id=target,
                    node_type=relation.target_type,
                    node_id=relation.target_id,
                    label=_label(relation.target_type, relation.target_id, request.node_label_max_chars),
                    group=relation.target_type,
                    score=0.0,
                ),
            )
            nodes_by_id[source].score += relation.strength * relation.confidence
            nodes_by_id[target].score += relation.strength * relation.confidence
            edges.append(
                VisualKnowledgeGraphEdge(
                    id=f"relation:{relation.id}",
                    source=source,
                    target=target,
                    label=relation.relation_type,
                    relation_type=relation.relation_type,
                    strength=relation.strength,
                    confidence=relation.confidence,
                    metadata={"description": relation.description, "evidence": relation.evidence, "active": relation.active},
                )
            )

        nodes = sorted(nodes_by_id.values(), key=lambda item: (-item.score, item.group, item.node_id))
        cytoscape = self._cytoscape(nodes, edges)
        mermaid = self._mermaid(nodes, edges)
        return VisualKnowledgeGraphResponse(
            agent_id=agent_id,
            world_id=request.world_id,
            node_count=len(nodes),
            edge_count=len(edges),
            nodes=nodes,
            edges=edges,
            legend={
                "memory": "remembered fact/event",
                "lorebook": "world/lore knowledge",
                "goal": "agent objective",
                "procedural_skill": "reusable behaviour/skill",
                "entity_state": "state of an entity or relationship",
            },
            cytoscape=cytoscape,
            mermaid=mermaid,
        )

    def _cytoscape(self, nodes: list[VisualKnowledgeGraphNode], edges: list[VisualKnowledgeGraphEdge]) -> dict[str, Any]:
        return {
            "elements": {
                "nodes": [{"data": node.model_dump()} for node in nodes],
                "edges": [{"data": edge.model_dump()} for edge in edges],
            }
        }

    def _mermaid(self, nodes: list[VisualKnowledgeGraphNode], edges: list[VisualKnowledgeGraphEdge]) -> str:
        lines = ["graph TD"]
        if not edges:
            lines.append('  empty["No relations found"]')
            return "\n".join(lines)
        node_ids = {node.id: _safe_mermaid_id(node.id) for node in nodes}
        for node in nodes:
            lines.append(f'  {node_ids[node.id]}["{node.label.replace(chr(34), chr(39))}"]')
        for edge in edges:
            lines.append(f'  {node_ids[edge.source]} -- "{edge.label}" --> {node_ids[edge.target]}')
        return "\n".join(lines)
