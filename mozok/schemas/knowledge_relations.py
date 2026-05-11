from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


COMMON_NODE_TYPES = [
    "memory",
    "lorebook",
    "entity_state",
    "goal",
    "procedural_skill",
    "skill",
    "plan_step",
    "agent",
    "entity",
    "faction",
    "quest",
    "location",
    "object",
    "concept",
]

COMMON_RELATION_TYPES = [
    "related_to",
    "about",
    "supports",
    "contradicts",
    "evidence_for",
    "caused_by",
    "causes",
    "depends_on",
    "blocks",
    "updates",
    "explains",
    "part_of",
    "similar_to",
    "duplicate_of",
    "supersedes",
    "derived_from",
    "motivates",
]


class KnowledgeRelationUpsert(BaseModel):
    """Create or update one directed knowledge relation edge.

    source_type/source_id --relation_type--> target_type/target_id

    Types are strings on purpose so projects can add their own node and relation
    categories without database migrations.
    """

    agent_id: str = Field(..., examples=["npc_alice", "narrator_001", "world_state"])
    world_id: str = Field("default", examples=["default", "from_like_world"])
    source_type: str = Field(..., examples=COMMON_NODE_TYPES)
    source_id: str = Field(..., examples=["42", "old_well", "hide_tunnel_secret"])
    relation_type: str = Field(..., examples=COMMON_RELATION_TYPES)
    target_type: str = Field(..., examples=COMMON_NODE_TYPES)
    target_id: str = Field(..., examples=["17", "old_well", "northern_forest_faction"])
    strength: float = Field(default=1.0, ge=0.0, le=1.0)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    description: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    validate_nodes: bool = Field(
        default=False,
        description=(
            "If true, known node types such as goal, lorebook, entity_state, and memory "
            "must already exist. Keep false for flexible/manual graph building."
        ),
    )


class KnowledgeRelationPatch(BaseModel):
    strength: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    description: str | None = None
    evidence: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    active: bool | None = None


class KnowledgeRelationRead(BaseModel):
    id: int
    agent_id: str
    world_id: str
    source_type: str
    source_id: str
    relation_type: str
    target_type: str
    target_id: str
    strength: float = 1.0
    confidence: float = 1.0
    description: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    active: bool = True

    @classmethod
    def from_record(cls, record):
        return cls(
            id=record.id,
            agent_id=record.agent_id,
            world_id=record.world_id or "default",
            source_type=record.source_type,
            source_id=record.source_id,
            relation_type=record.relation_type,
            target_type=record.target_type,
            target_id=record.target_id,
            strength=float(record.strength if record.strength is not None else 1.0),
            confidence=float(record.confidence if record.confidence is not None else 1.0),
            description=record.description or "",
            evidence=dict(record.evidence_json or {}),
            metadata=dict(record.metadata_json or {}),
            active=bool(record.active),
        )

    class Config:
        from_attributes = True


class KnowledgeRelationContextResponse(BaseModel):
    agent_id: str
    world_id: str | None = None
    count: int
    lines: list[str]
    relations: list[KnowledgeRelationRead]


class KnowledgeNodeResolution(BaseModel):
    found: bool
    node_type: str
    node_id: str
    title: str = ""
    summary: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
    message: str = ""


class KnowledgeRelationResolvedResponse(BaseModel):
    relation: KnowledgeRelationRead
    source: KnowledgeNodeResolution
    target: KnowledgeNodeResolution


class KnowledgeRelationNeighborhoodResponse(BaseModel):
    agent_id: str
    world_id: str | None = None
    node_type: str
    node_id: str
    direction: str
    count: int
    lines: list[str]
    relations: list[KnowledgeRelationRead]


class KnowledgeGraphRootNode(BaseModel):
    """Start node for graph traversal/debugging."""

    node_type: str = Field(..., examples=["memory", "goal", "lorebook", "entity_state"])
    node_id: str = Field(..., examples=["42", "hide_tunnel_secret", "old_well"])


class KnowledgeRelationGraphDebugRequest(BaseModel):
    """Read-only multi-hop graph traversal request.

    This powers graph debugging and can also be reused by context assembly to
    avoid uncontrolled relation fan-out. It never creates, updates, archives, or
    deletes graph edges.
    """

    world_id: str | None = Field(default="default", examples=["default", "from_like_world"])
    roots: list[KnowledgeGraphRootNode] = Field(
        default_factory=list,
        description="Root knowledge nodes to traverse from.",
    )
    direction: str = Field(default="both", examples=["both", "outgoing", "incoming"])
    max_depth: int = Field(default=2, ge=1, le=5)
    max_relations: int = Field(default=50, ge=1, le=300)
    per_node_limit: int = Field(default=12, ge=1, le=100)
    estimated_token_budget: int | None = Field(
        default=None,
        ge=1,
        le=20000,
        description="Optional approximate prompt-token budget for relation lines.",
    )
    relation_types: list[str] | None = Field(
        default=None,
        description="Optional allow-list of relation types to traverse.",
        examples=[["depends_on", "evidence_for", "supports"]],
    )
    min_strength: float = Field(default=0.0, ge=0.0, le=1.0)
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    include_inactive: bool = False
    resolve_nodes: bool = Field(
        default=False,
        description="If true, attempt to resolve known node types into titles/summaries for debugging.",
    )


class KnowledgeGraphNodeRead(BaseModel):
    node_type: str
    node_id: str
    depth: int
    score: float = 0.0
    first_seen_via_relation_id: int | None = None
    resolved: KnowledgeNodeResolution | None = None


class KnowledgeGraphPathRead(BaseModel):
    depth: int
    nodes: list[str]
    relation_ids: list[int]
    score: float = 0.0


class KnowledgeGraphCycleRead(BaseModel):
    detected_at_depth: int
    nodes: list[str]
    relation_ids: list[int]
    relation_id: int


class KnowledgeGraphRerankHint(BaseModel):
    node_type: str
    node_id: str
    score: float
    min_depth: int
    relation_count: int
    strongest_relation: float
    confidence: float


class KnowledgeRelationGraphDebugResponse(BaseModel):
    agent_id: str
    world_id: str | None = None
    roots: list[KnowledgeGraphRootNode]
    direction: str
    max_depth: int
    node_count: int
    relation_count: int
    cycle_count: int
    nodes: list[KnowledgeGraphNodeRead]
    relations: list[KnowledgeRelationRead]
    relation_lines: list[str]
    paths: list[KnowledgeGraphPathRead]
    cycles: list[KnowledgeGraphCycleRead]
    rerank_hints: list[KnowledgeGraphRerankHint]
    traversal_report: dict[str, Any] = Field(default_factory=dict)


class KnowledgeRelationAutoCreateItem(BaseModel):
    """A reviewed graph edge suggestion that may be created explicitly."""

    source_type: str
    source_id: str
    relation_type: str
    target_type: str
    target_id: str
    strength: float = Field(default=0.7, ge=0.0, le=1.0)
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    description: str = ""
    evidence: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class KnowledgeRelationAutoCreateRequest(BaseModel):
    """Create reviewed relation suggestions in one safe batch.

    This is intended for future maintenance/summariser/dedup UI flows. It is not
    automatic unless a caller explicitly sends reviewed suggestions here.
    """

    world_id: str = Field(default="default")
    suggestions: list[KnowledgeRelationAutoCreateItem] = Field(default_factory=list)
    validate_nodes: bool = False
    dry_run: bool = Field(default=False, description="If true, validate/preview only and do not write SQL.")


class KnowledgeRelationAutoCreateResponse(BaseModel):
    agent_id: str
    world_id: str
    dry_run: bool
    requested: int
    created: int
    updated: int
    skipped: int
    errors: list[str] = Field(default_factory=list)
    relation_ids: list[int] = Field(default_factory=list)
    relations: list[KnowledgeRelationRead] = Field(default_factory=list)
