from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class VisualKnowledgeGraphRequest(BaseModel):
    world_id: str | None = "default"
    include_inactive: bool = False
    relation_types: list[str] | None = None
    min_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    limit: int = Field(default=150, ge=1, le=1000)
    node_label_max_chars: int = Field(default=42, ge=8, le=120)


class VisualKnowledgeGraphNode(BaseModel):
    id: str
    node_type: str
    node_id: str
    label: str
    group: str
    score: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class VisualKnowledgeGraphEdge(BaseModel):
    id: str
    source: str
    target: str
    label: str
    relation_type: str
    strength: float = 1.0
    confidence: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class VisualKnowledgeGraphResponse(BaseModel):
    agent_id: str
    world_id: str | None = None
    node_count: int = 0
    edge_count: int = 0
    nodes: list[VisualKnowledgeGraphNode] = Field(default_factory=list)
    edges: list[VisualKnowledgeGraphEdge] = Field(default_factory=list)
    legend: dict[str, str] = Field(default_factory=dict)
    export_formats: list[str] = Field(default_factory=lambda: ["json", "cytoscape", "mermaid"])
    cytoscape: dict[str, Any] = Field(default_factory=dict)
    mermaid: str = ""
