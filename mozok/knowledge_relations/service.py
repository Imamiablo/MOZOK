from __future__ import annotations

from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Iterable

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from mozok.db.models import AgentRecord, MemoryRecord
from mozok.entity_state.models import AgentEntityStateRecord
from mozok.goals.models import AgentGoalRecord
from mozok.knowledge_relations.models import KnowledgeRelationRecord
from mozok.lorebook.models import LorebookEntryRecord
from mozok.procedural_skills.models import AgentProceduralSkillRecord
from mozok.memory.policy import fresh_default_memory_policy
from mozok.schemas.knowledge_relations import (
    KnowledgeNodeResolution,
    KnowledgeRelationPatch,
    KnowledgeGraphCycleRead,
    KnowledgeGraphNodeRead,
    KnowledgeGraphPathRead,
    KnowledgeGraphRerankHint,
    KnowledgeGraphRootNode,
    KnowledgeRelationAutoCreateRequest,
    KnowledgeRelationAutoCreateResponse,
    KnowledgeRelationGraphDebugRequest,
    KnowledgeRelationGraphDebugResponse,
    KnowledgeRelationRead,
    KnowledgeRelationUpsert,
)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _clean_key(value: str, fallback: str = "item") -> str:
    clean = " ".join(str(value or "").strip().split())
    return clean or fallback


def _clean_text(value: str, max_chars: int | None = None) -> str:
    clean = " ".join(str(value or "").strip().split())
    if max_chars is not None and len(clean) > max_chars:
        return clean[: max_chars - 3] + "..."
    return clean


def _clamp_unit(value: float | int | None, fallback: float = 1.0) -> float:
    try:
        number = float(fallback if value is None else value)
    except (TypeError, ValueError):
        number = float(fallback)
    return max(0.0, min(1.0, number))


def _try_int(value: str | int | None) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _confidence_label(value: float | int | None) -> str:
    confidence = _clamp_unit(value, 1.0)
    if confidence >= 0.8:
        return "high"
    if confidence >= 0.45:
        return "medium"
    return "low"


def format_knowledge_relation_for_prompt_line(relation: KnowledgeRelationRecord | KnowledgeRelationRead | Any) -> str:
    """Format one relation edge as a compact prompt/debug line."""

    source_type = _clean_key(getattr(relation, "source_type", "source"), "source")
    source_id = _clean_key(getattr(relation, "source_id", ""), "unknown")
    relation_type = _clean_key(getattr(relation, "relation_type", "related_to"), "related_to")
    target_type = _clean_key(getattr(relation, "target_type", "target"), "target")
    target_id = _clean_key(getattr(relation, "target_id", ""), "unknown")
    strength = _clamp_unit(getattr(relation, "strength", 1.0), 1.0)
    confidence = _clamp_unit(getattr(relation, "confidence", 1.0), 1.0)
    description = _clean_text(getattr(relation, "description", ""), 260)

    line = (
        f'- {source_type}:"{source_id}" {relation_type} {target_type}:"{target_id}" '
        f"| strength={strength:.2f} confidence={confidence:.2f} ({_confidence_label(confidence)})"
    )
    if description:
        line += f" | reason: {description}"
    return line


class KnowledgeRelationService:
    """CRUD/service layer for generic knowledge graph edges."""

    def __init__(self, db: Session):
        self.db = db

    def _ensure_agent(self, agent_id: str) -> AgentRecord:
        clean_agent_id = _clean_key(agent_id, "default_agent")
        agent = self.db.get(AgentRecord, clean_agent_id)
        if agent is not None:
            return agent

        agent = AgentRecord(
            id=clean_agent_id,
            name=clean_agent_id,
            description="Default Mozok agent.",
            personality="Helpful, curious, and remembers relevant past events.",
            system_prompt="Use memories when relevant. Do not invent memories.",
            state_json={},
            metadata_json={
                "memory_policy": fresh_default_memory_policy(),
                "memory_maintenance": {},
            },
        )
        self.db.add(agent)
        self.db.commit()
        self.db.refresh(agent)
        return agent

    def upsert(self, data: KnowledgeRelationUpsert) -> KnowledgeRelationRecord:
        agent_id = _clean_key(data.agent_id, "default_agent")
        world_id = _clean_key(data.world_id, "default")
        source_type = _clean_key(data.source_type, "source")
        source_id = _clean_key(data.source_id, "unknown")
        relation_type = _clean_key(data.relation_type, "related_to")
        target_type = _clean_key(data.target_type, "target")
        target_id = _clean_key(data.target_id, "unknown")
        self._ensure_agent(agent_id)

        if data.validate_nodes:
            self.validate_edge_nodes(
                agent_id=agent_id,
                world_id=world_id,
                source_type=source_type,
                source_id=source_id,
                target_type=target_type,
                target_id=target_id,
            )

        record = (
            self.db.query(KnowledgeRelationRecord)
            .filter(
                KnowledgeRelationRecord.agent_id == agent_id,
                KnowledgeRelationRecord.world_id == world_id,
                KnowledgeRelationRecord.source_type == source_type,
                KnowledgeRelationRecord.source_id == source_id,
                KnowledgeRelationRecord.relation_type == relation_type,
                KnowledgeRelationRecord.target_type == target_type,
                KnowledgeRelationRecord.target_id == target_id,
            )
            .one_or_none()
        )

        now = utc_now()
        if record is None:
            record = KnowledgeRelationRecord(
                agent_id=agent_id,
                world_id=world_id,
                source_type=source_type,
                source_id=source_id,
                relation_type=relation_type,
                target_type=target_type,
                target_id=target_id,
                created_at=now,
            )
            self.db.add(record)

        record.strength = _clamp_unit(data.strength, 1.0)
        record.confidence = _clamp_unit(data.confidence, 1.0)
        record.description = data.description.strip()
        record.evidence_json = dict(data.evidence or {})
        record.metadata_json = dict(data.metadata or {})
        record.active = True
        record.updated_at = now

        self.db.commit()
        self.db.refresh(record)
        return record

    def patch(self, relation_id: int, data: KnowledgeRelationPatch) -> KnowledgeRelationRecord | None:
        record = self.db.get(KnowledgeRelationRecord, int(relation_id))
        if record is None:
            return None

        if data.strength is not None:
            record.strength = _clamp_unit(data.strength, record.strength)
        if data.confidence is not None:
            record.confidence = _clamp_unit(data.confidence, record.confidence)
        if data.description is not None:
            record.description = data.description.strip()
        if data.evidence is not None:
            record.evidence_json = dict(data.evidence or {})
        if data.metadata is not None:
            record.metadata_json = dict(data.metadata or {})
        if data.active is not None:
            record.active = bool(data.active)

        record.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(record)
        return record

    def soft_delete(self, relation_id: int) -> bool:
        record = self.db.get(KnowledgeRelationRecord, int(relation_id))
        if record is None:
            return False
        record.active = False
        record.updated_at = utc_now()
        self.db.commit()
        return True

    def list_relations(
        self,
        agent_id: str,
        world_id: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        relation_type: str | None = None,
        include_inactive: bool = False,
        limit: int = 50,
    ) -> list[KnowledgeRelationRecord]:
        query = self.db.query(KnowledgeRelationRecord).filter(
            KnowledgeRelationRecord.agent_id == _clean_key(agent_id, "default_agent")
        )
        if world_id:
            query = query.filter(KnowledgeRelationRecord.world_id == _clean_key(world_id, "default"))
        if not include_inactive:
            query = query.filter(KnowledgeRelationRecord.active == True)  # noqa: E712
        if source_type:
            query = query.filter(KnowledgeRelationRecord.source_type == _clean_key(source_type, "source"))
        if source_id:
            query = query.filter(KnowledgeRelationRecord.source_id == _clean_key(source_id, "unknown"))
        if target_type:
            query = query.filter(KnowledgeRelationRecord.target_type == _clean_key(target_type, "target"))
        if target_id:
            query = query.filter(KnowledgeRelationRecord.target_id == _clean_key(target_id, "unknown"))
        if relation_type:
            query = query.filter(KnowledgeRelationRecord.relation_type == _clean_key(relation_type, "related_to"))

        return (
            query.order_by(
                KnowledgeRelationRecord.strength.desc(),
                KnowledgeRelationRecord.confidence.desc(),
                KnowledgeRelationRecord.updated_at.desc(),
            )
            .limit(max(1, min(int(limit), 200)))
            .all()
        )

    def list_neighborhood(
        self,
        agent_id: str,
        node_type: str,
        node_id: str,
        world_id: str | None = None,
        direction: str = "both",
        include_inactive: bool = False,
        limit: int = 50,
    ) -> list[KnowledgeRelationRecord]:
        safe_direction = _clean_key(direction, "both").lower()
        safe_type = _clean_key(node_type, "node")
        safe_id = _clean_key(node_id, "unknown")

        query = self.db.query(KnowledgeRelationRecord).filter(
            KnowledgeRelationRecord.agent_id == _clean_key(agent_id, "default_agent")
        )
        if world_id:
            query = query.filter(KnowledgeRelationRecord.world_id == _clean_key(world_id, "default"))
        if not include_inactive:
            query = query.filter(KnowledgeRelationRecord.active == True)  # noqa: E712

        outgoing = and_(
            KnowledgeRelationRecord.source_type == safe_type,
            KnowledgeRelationRecord.source_id == safe_id,
        )
        incoming = and_(
            KnowledgeRelationRecord.target_type == safe_type,
            KnowledgeRelationRecord.target_id == safe_id,
        )
        if safe_direction == "outgoing":
            query = query.filter(outgoing)
        elif safe_direction == "incoming":
            query = query.filter(incoming)
        else:
            query = query.filter(or_(outgoing, incoming))

        return (
            query.order_by(
                KnowledgeRelationRecord.strength.desc(),
                KnowledgeRelationRecord.confidence.desc(),
                KnowledgeRelationRecord.updated_at.desc(),
            )
            .limit(max(1, min(int(limit), 200)))
            .all()
        )

    def list_related_to_nodes(
        self,
        agent_id: str,
        node_refs: Iterable[tuple[str, str]],
        world_id: str | None = None,
        exclude_ids: set[int] | None = None,
        limit: int = 10,
    ) -> list[KnowledgeRelationRecord]:
        """Return one-hop relations touching any selected context node.

        This is deliberately one-hop only. Multi-hop traversal belongs to a later
        budget-aware graph retrieval system.
        """

        cleaned_refs = []
        seen_refs = set()
        for node_type, node_id in node_refs:
            safe_type = _clean_key(node_type, "node")
            safe_id = _clean_key(node_id, "unknown")
            key = (safe_type, safe_id)
            if key not in seen_refs:
                seen_refs.add(key)
                cleaned_refs.append(key)

        if not cleaned_refs:
            return []

        predicates = []
        for node_type, node_id in cleaned_refs[:80]:
            predicates.append(
                and_(
                    KnowledgeRelationRecord.source_type == node_type,
                    KnowledgeRelationRecord.source_id == node_id,
                )
            )
            predicates.append(
                and_(
                    KnowledgeRelationRecord.target_type == node_type,
                    KnowledgeRelationRecord.target_id == node_id,
                )
            )

        query = self.db.query(KnowledgeRelationRecord).filter(
            KnowledgeRelationRecord.agent_id == _clean_key(agent_id, "default_agent"),
            KnowledgeRelationRecord.active == True,  # noqa: E712
            or_(*predicates),
        )
        if world_id:
            query = query.filter(KnowledgeRelationRecord.world_id == _clean_key(world_id, "default"))
        if exclude_ids:
            query = query.filter(~KnowledgeRelationRecord.id.in_(set(exclude_ids)))

        return (
            query.order_by(
                KnowledgeRelationRecord.strength.desc(),
                KnowledgeRelationRecord.confidence.desc(),
                KnowledgeRelationRecord.updated_at.desc(),
            )
            .limit(max(1, min(int(limit), 100)))
            .all()
        )


    def traverse_graph(
        self,
        agent_id: str,
        request: KnowledgeRelationGraphDebugRequest,
    ) -> KnowledgeRelationGraphDebugResponse:
        """Traverse the agent knowledge graph with depth, cycle, and budget guards.

        The traversal is read-only and deliberately deterministic. It is suitable
        both for the graph debug endpoint and for budget-aware context expansion:
        strong/confident edges are explored first, cycles are reported instead of
        followed forever, and optional token budgets stop relation fan-out before
        prompt assembly becomes bloated.
        """

        safe_agent_id = _clean_key(agent_id, "default_agent")
        safe_world_id = _clean_key(request.world_id or "default", "default")
        safe_direction = _clean_key(request.direction, "both").lower()
        if safe_direction not in {"both", "outgoing", "incoming"}:
            safe_direction = "both"

        roots = self._normalise_root_nodes(request.roots)
        max_depth = max(1, min(int(request.max_depth), 5))
        max_relations = max(1, min(int(request.max_relations), 300))
        per_node_limit = max(1, min(int(request.per_node_limit), 100))
        allowed_relation_types = {
            _clean_key(value, "related_to") for value in (request.relation_types or []) if str(value).strip()
        }

        relation_records: list[KnowledgeRelationRecord] = []
        seen_relation_ids: set[int] = set()
        node_depth: dict[tuple[str, str], int] = {root: 0 for root in roots}
        node_first_relation: dict[tuple[str, str], int | None] = {root: None for root in roots}
        node_scores: dict[tuple[str, str], float] = defaultdict(float)
        relation_counts_by_node: dict[tuple[str, str], int] = defaultdict(int)
        strongest_by_node: dict[tuple[str, str], float] = defaultdict(float)
        confidence_by_node: dict[tuple[str, str], float] = defaultdict(float)
        paths: list[KnowledgeGraphPathRead] = []
        cycles: list[KnowledgeGraphCycleRead] = []

        estimated_used_tokens = 0
        skipped_for_budget = 0
        skipped_for_threshold = 0
        skipped_seen_edges = 0
        stopped_by_relation_limit = False
        frontier = deque((root, 0, [], [root], 1.0) for root in roots)

        while frontier:
            current, depth, path_relation_ids, path_nodes, path_score = frontier.popleft()
            if depth >= max_depth:
                continue
            if len(relation_records) >= max_relations:
                stopped_by_relation_limit = True
                break

            edges = self._edges_for_node(
                agent_id=safe_agent_id,
                world_id=safe_world_id,
                node=current,
                direction=safe_direction,
                include_inactive=request.include_inactive,
                limit=per_node_limit,
            )
            for relation in edges:
                if len(relation_records) >= max_relations:
                    stopped_by_relation_limit = True
                    break
                if relation.id in seen_relation_ids:
                    skipped_seen_edges += 1
                    continue
                if allowed_relation_types and relation.relation_type not in allowed_relation_types:
                    skipped_for_threshold += 1
                    continue
                if float(relation.strength or 0.0) < float(request.min_strength):
                    skipped_for_threshold += 1
                    continue
                if float(relation.confidence or 0.0) < float(request.min_confidence):
                    skipped_for_threshold += 1
                    continue

                next_node = self._other_node_for_relation(relation, current, safe_direction)
                if next_node is None:
                    continue

                line = format_knowledge_relation_for_prompt_line(relation)
                estimated_tokens = self._estimate_relation_tokens(line)
                if request.estimated_token_budget is not None and estimated_used_tokens + estimated_tokens > int(request.estimated_token_budget):
                    skipped_for_budget += 1
                    continue

                seen_relation_ids.add(int(relation.id))
                relation_records.append(relation)
                estimated_used_tokens += estimated_tokens

                next_depth = depth + 1
                edge_score = self._edge_traversal_score(relation, next_depth)
                cumulative_score = round(path_score * edge_score, 6)
                node_scores[next_node] += edge_score
                relation_counts_by_node[next_node] += 1
                strongest_by_node[next_node] = max(strongest_by_node[next_node], float(relation.strength or 0.0))
                confidence_by_node[next_node] = max(confidence_by_node[next_node], float(relation.confidence or 0.0))

                new_relation_ids = list(path_relation_ids) + [int(relation.id)]
                new_path_nodes = list(path_nodes) + [next_node]
                paths.append(
                    KnowledgeGraphPathRead(
                        depth=next_depth,
                        nodes=[self._node_label(node) for node in new_path_nodes],
                        relation_ids=new_relation_ids,
                        score=cumulative_score,
                    )
                )

                if next_node in path_nodes:
                    cycle_start = path_nodes.index(next_node)
                    cycle_nodes = path_nodes[cycle_start:] + [next_node]
                    cycles.append(
                        KnowledgeGraphCycleRead(
                            detected_at_depth=next_depth,
                            nodes=[self._node_label(node) for node in cycle_nodes],
                            relation_ids=new_relation_ids,
                            relation_id=int(relation.id),
                        )
                    )
                    continue

                if next_node not in node_depth or next_depth < node_depth[next_node]:
                    node_depth[next_node] = next_depth
                    node_first_relation[next_node] = int(relation.id)

                if next_depth < max_depth and node_depth.get(next_node, next_depth) >= next_depth:
                    frontier.append((next_node, next_depth, new_relation_ids, new_path_nodes, cumulative_score))

        relation_reads = reads_from_records(relation_records)
        nodes = self._graph_nodes(
            agent_id=safe_agent_id,
            world_id=safe_world_id,
            node_depth=node_depth,
            node_scores=node_scores,
            node_first_relation=node_first_relation,
            resolve_nodes=bool(request.resolve_nodes),
        )
        rerank_hints = self._graph_rerank_hints(
            node_depth=node_depth,
            node_scores=node_scores,
            relation_counts_by_node=relation_counts_by_node,
            strongest_by_node=strongest_by_node,
            confidence_by_node=confidence_by_node,
        )

        return KnowledgeRelationGraphDebugResponse(
            agent_id=safe_agent_id,
            world_id=safe_world_id,
            roots=[KnowledgeGraphRootNode(node_type=node_type, node_id=node_id) for node_type, node_id in roots],
            direction=safe_direction,
            max_depth=max_depth,
            node_count=len(nodes),
            relation_count=len(relation_reads),
            cycle_count=len(cycles),
            nodes=nodes,
            relations=relation_reads,
            relation_lines=[format_knowledge_relation_for_prompt_line(relation) for relation in relation_reads],
            paths=paths,
            cycles=cycles,
            rerank_hints=rerank_hints,
            traversal_report={
                "read_only": True,
                "multi_hop": max_depth > 1,
                "budget_aware": request.estimated_token_budget is not None,
                "estimated_token_budget": request.estimated_token_budget,
                "estimated_used_tokens": estimated_used_tokens,
                "skipped_for_budget": skipped_for_budget,
                "skipped_for_threshold": skipped_for_threshold,
                "skipped_seen_edges": skipped_seen_edges,
                "stopped_by_relation_limit": stopped_by_relation_limit,
                "per_node_limit": per_node_limit,
                "max_relations": max_relations,
                "cycle_detection": "enabled",
                "relation_aware_reranking_hints": len(rerank_hints),
            },
        )

    def create_reviewed_relations(
        self,
        agent_id: str,
        request: KnowledgeRelationAutoCreateRequest,
    ) -> KnowledgeRelationAutoCreateResponse:
        """Create reviewed graph suggestions from maintenance/summariser tooling.

        This is a small safe bridge: automatic systems may *suggest* relation
        payloads, but this method creates them only when a caller explicitly sends
        a batch. The MemoryService summariser also creates conservative
        ``summarised_by`` / ``derived_from`` edges internally for its own summary
        memories.
        """

        safe_agent_id = _clean_key(agent_id, "default_agent")
        safe_world_id = _clean_key(request.world_id, "default")
        created = 0
        updated = 0
        skipped = 0
        errors: list[str] = []
        relation_ids: list[int] = []
        relations: list[KnowledgeRelationRead] = []

        for index, suggestion in enumerate(request.suggestions):
            try:
                payload = KnowledgeRelationUpsert(
                    agent_id=safe_agent_id,
                    world_id=safe_world_id,
                    source_type=suggestion.source_type,
                    source_id=suggestion.source_id,
                    relation_type=suggestion.relation_type,
                    target_type=suggestion.target_type,
                    target_id=suggestion.target_id,
                    strength=suggestion.strength,
                    confidence=suggestion.confidence,
                    description=suggestion.description,
                    evidence=suggestion.evidence,
                    metadata={**dict(suggestion.metadata or {}), "created_from": "reviewed_auto_create"},
                    validate_nodes=request.validate_nodes,
                )
                if request.dry_run:
                    if request.validate_nodes:
                        self.validate_edge_nodes(
                            agent_id=safe_agent_id,
                            world_id=safe_world_id,
                            source_type=payload.source_type,
                            source_id=payload.source_id,
                            target_type=payload.target_type,
                            target_id=payload.target_id,
                        )
                    skipped += 1
                    continue

                before = (
                    self.db.query(KnowledgeRelationRecord)
                    .filter(
                        KnowledgeRelationRecord.agent_id == safe_agent_id,
                        KnowledgeRelationRecord.world_id == safe_world_id,
                        KnowledgeRelationRecord.source_type == payload.source_type,
                        KnowledgeRelationRecord.source_id == payload.source_id,
                        KnowledgeRelationRecord.relation_type == payload.relation_type,
                        KnowledgeRelationRecord.target_type == payload.target_type,
                        KnowledgeRelationRecord.target_id == payload.target_id,
                    )
                    .one_or_none()
                )
                record = self.upsert(payload)
                relation_ids.append(int(record.id))
                relations.append(KnowledgeRelationRead.from_record(record))
                if before is None:
                    created += 1
                else:
                    updated += 1
            except Exception as exc:  # keep batch creation best-effort and inspectable
                errors.append(f"suggestion[{index}]: {exc}")

        return KnowledgeRelationAutoCreateResponse(
            agent_id=safe_agent_id,
            world_id=safe_world_id,
            dry_run=bool(request.dry_run),
            requested=len(request.suggestions),
            created=created,
            updated=updated,
            skipped=skipped,
            errors=errors,
            relation_ids=relation_ids,
            relations=relations,
        )

    def _normalise_root_nodes(self, roots: Iterable[KnowledgeGraphRootNode]) -> list[tuple[str, str]]:
        normalised: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for root in roots:
            key = (_clean_key(root.node_type, "node"), _clean_key(root.node_id, "unknown"))
            if key not in seen:
                seen.add(key)
                normalised.append(key)
        return normalised

    def _edges_for_node(
        self,
        *,
        agent_id: str,
        world_id: str,
        node: tuple[str, str],
        direction: str,
        include_inactive: bool,
        limit: int,
    ) -> list[KnowledgeRelationRecord]:
        node_type, node_id = node
        query = self.db.query(KnowledgeRelationRecord).filter(
            KnowledgeRelationRecord.agent_id == agent_id,
            KnowledgeRelationRecord.world_id == world_id,
        )
        if not include_inactive:
            query = query.filter(KnowledgeRelationRecord.active == True)  # noqa: E712

        outgoing = and_(KnowledgeRelationRecord.source_type == node_type, KnowledgeRelationRecord.source_id == node_id)
        incoming = and_(KnowledgeRelationRecord.target_type == node_type, KnowledgeRelationRecord.target_id == node_id)
        if direction == "outgoing":
            query = query.filter(outgoing)
        elif direction == "incoming":
            query = query.filter(incoming)
        else:
            query = query.filter(or_(outgoing, incoming))

        return (
            query.order_by(
                (KnowledgeRelationRecord.strength * KnowledgeRelationRecord.confidence).desc(),
                KnowledgeRelationRecord.updated_at.desc(),
            )
            .limit(limit)
            .all()
        )

    def _other_node_for_relation(
        self,
        relation: KnowledgeRelationRecord,
        current: tuple[str, str],
        direction: str,
    ) -> tuple[str, str] | None:
        source = (_clean_key(relation.source_type, "source"), _clean_key(relation.source_id, "unknown"))
        target = (_clean_key(relation.target_type, "target"), _clean_key(relation.target_id, "unknown"))
        if direction == "outgoing":
            return target if source == current else None
        if direction == "incoming":
            return source if target == current else None
        if source == current:
            return target
        if target == current:
            return source
        return None

    def _edge_traversal_score(self, relation: KnowledgeRelationRecord, depth: int) -> float:
        strength = _clamp_unit(relation.strength, 1.0)
        confidence = _clamp_unit(relation.confidence, 1.0)
        depth_decay = 0.72 ** max(0, depth - 1)
        return round(strength * confidence * depth_decay, 6)

    def _estimate_relation_tokens(self, line: str) -> int:
        return max(8, int(len(line) / 4.0) + 1)

    def _node_label(self, node: tuple[str, str]) -> str:
        return f"{node[0]}:{node[1]}"

    def _graph_nodes(
        self,
        *,
        agent_id: str,
        world_id: str,
        node_depth: dict[tuple[str, str], int],
        node_scores: dict[tuple[str, str], float],
        node_first_relation: dict[tuple[str, str], int | None],
        resolve_nodes: bool,
    ) -> list[KnowledgeGraphNodeRead]:
        nodes: list[KnowledgeGraphNodeRead] = []
        for node, depth in sorted(node_depth.items(), key=lambda item: (item[1], item[0][0], item[0][1])):
            resolved = None
            if resolve_nodes:
                resolved = self.resolve_node(agent_id=agent_id, world_id=world_id, node_type=node[0], node_id=node[1])
            nodes.append(
                KnowledgeGraphNodeRead(
                    node_type=node[0],
                    node_id=node[1],
                    depth=int(depth),
                    score=round(float(node_scores.get(node, 0.0)), 6),
                    first_seen_via_relation_id=node_first_relation.get(node),
                    resolved=resolved,
                )
            )
        return nodes

    def _graph_rerank_hints(
        self,
        *,
        node_depth: dict[tuple[str, str], int],
        node_scores: dict[tuple[str, str], float],
        relation_counts_by_node: dict[tuple[str, str], int],
        strongest_by_node: dict[tuple[str, str], float],
        confidence_by_node: dict[tuple[str, str], float],
    ) -> list[KnowledgeGraphRerankHint]:
        hints: list[KnowledgeGraphRerankHint] = []
        for node, score in node_scores.items():
            if score <= 0:
                continue
            hints.append(
                KnowledgeGraphRerankHint(
                    node_type=node[0],
                    node_id=node[1],
                    score=round(float(score), 6),
                    min_depth=int(node_depth.get(node, 999)),
                    relation_count=int(relation_counts_by_node.get(node, 0)),
                    strongest_relation=round(float(strongest_by_node.get(node, 0.0)), 6),
                    confidence=round(float(confidence_by_node.get(node, 0.0)), 6),
                )
            )
        hints.sort(key=lambda item: (item.min_depth, -item.score, item.node_type, item.node_id))
        return hints

    def format_context_lines(
        self,
        agent_id: str,
        world_id: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        relation_type: str | None = None,
        limit: int = 10,
    ) -> list[str]:
        records = self.list_relations(
            agent_id=agent_id,
            world_id=world_id,
            source_type=source_type,
            source_id=source_id,
            target_type=target_type,
            target_id=target_id,
            relation_type=relation_type,
            include_inactive=False,
            limit=limit,
        )
        return [format_knowledge_relation_for_prompt_line(record) for record in records]

    def validate_edge_nodes(
        self,
        agent_id: str,
        world_id: str,
        source_type: str,
        source_id: str,
        target_type: str,
        target_id: str,
    ) -> None:
        source = self.resolve_node(agent_id=agent_id, world_id=world_id, node_type=source_type, node_id=source_id)
        target = self.resolve_node(agent_id=agent_id, world_id=world_id, node_type=target_type, node_id=target_id)
        missing = []
        if not source.found:
            missing.append(f"source {source_type}:{source_id}")
        if not target.found:
            missing.append(f"target {target_type}:{target_id}")
        if missing:
            raise ValueError("Knowledge relation node validation failed: " + ", ".join(missing))

    def resolve_relation(self, relation_id: int) -> tuple[KnowledgeRelationRecord | None, KnowledgeNodeResolution | None, KnowledgeNodeResolution | None]:
        relation = self.db.get(KnowledgeRelationRecord, int(relation_id))
        if relation is None:
            return None, None, None
        source = self.resolve_node(
            agent_id=relation.agent_id,
            world_id=relation.world_id,
            node_type=relation.source_type,
            node_id=relation.source_id,
        )
        target = self.resolve_node(
            agent_id=relation.agent_id,
            world_id=relation.world_id,
            node_type=relation.target_type,
            node_id=relation.target_id,
        )
        return relation, source, target

    def resolve_node(
        self,
        agent_id: str,
        world_id: str | None,
        node_type: str,
        node_id: str,
    ) -> KnowledgeNodeResolution:
        safe_type = _clean_key(node_type, "node")
        safe_id = _clean_key(node_id, "unknown")
        safe_agent_id = _clean_key(agent_id, "default_agent")
        safe_world_id = _clean_key(world_id or "default", "default")

        try:
            if safe_type == "goal":
                return self._resolve_goal(safe_agent_id, safe_id)
            if safe_type == "lorebook":
                return self._resolve_lorebook(safe_world_id, safe_id)
            if safe_type == "entity_state":
                return self._resolve_entity_state(safe_agent_id, safe_id)
            if safe_type == "memory":
                return self._resolve_memory(safe_agent_id, safe_id)
            if safe_type == "procedural_skill" or safe_type == "skill":
                return self._resolve_procedural_skill(safe_agent_id, safe_id)
            if safe_type == "agent":
                return self._resolve_agent(safe_id)
        except Exception as exc:  # defensive: debug resolution should not crash context building
            return KnowledgeNodeResolution(
                found=False,
                node_type=safe_type,
                node_id=safe_id,
                message=f"Resolution failed: {exc}",
            )

        return KnowledgeNodeResolution(
            found=True,
            node_type=safe_type,
            node_id=safe_id,
            title=safe_id,
            summary=f"Custom/unvalidated node type: {safe_type}",
            data={},
        )

    def _resolve_goal(self, agent_id: str, node_id: str) -> KnowledgeNodeResolution:
        record = None
        int_id = _try_int(node_id)
        if int_id is not None:
            record = self.db.get(AgentGoalRecord, int_id)
        if record is None:
            record = (
                self.db.query(AgentGoalRecord)
                .filter(
                    AgentGoalRecord.agent_id == agent_id,
                    AgentGoalRecord.goal_key == node_id,
                    AgentGoalRecord.active == True,  # noqa: E712
                )
                .one_or_none()
            )
        if record is None:
            return KnowledgeNodeResolution(found=False, node_type="goal", node_id=node_id, message="Goal not found")
        return KnowledgeNodeResolution(
            found=True,
            node_type="goal",
            node_id=node_id,
            title=record.title or record.goal_key,
            summary=_clean_text(record.description or record.notes or record.goal_key, 280),
            data={"id": record.id, "agent_id": record.agent_id, "goal_key": record.goal_key, "status": record.status, "priority": record.priority},
        )

    def _resolve_lorebook(self, world_id: str, node_id: str) -> KnowledgeNodeResolution:
        record = None
        int_id = _try_int(node_id)
        if int_id is not None:
            record = self.db.get(LorebookEntryRecord, int_id)
        if record is None:
            record = (
                self.db.query(LorebookEntryRecord)
                .filter(
                    LorebookEntryRecord.world_id == world_id,
                    LorebookEntryRecord.entry_key == node_id,
                    LorebookEntryRecord.is_active == True,  # noqa: E712
                )
                .one_or_none()
            )
        if record is None:
            return KnowledgeNodeResolution(found=False, node_type="lorebook", node_id=node_id, message="Lorebook entry not found")
        return KnowledgeNodeResolution(
            found=True,
            node_type="lorebook",
            node_id=node_id,
            title=record.title or record.entry_key,
            summary=_clean_text(record.content or "", 280),
            data={"id": record.id, "world_id": record.world_id, "entry_key": record.entry_key, "category": record.category, "visibility": record.visibility},
        )

    def _resolve_entity_state(self, agent_id: str, node_id: str) -> KnowledgeNodeResolution:
        record = None
        int_id = _try_int(node_id)
        if int_id is not None:
            record = self.db.get(AgentEntityStateRecord, int_id)
        if record is None:
            record = (
                self.db.query(AgentEntityStateRecord)
                .filter(
                    AgentEntityStateRecord.agent_id == agent_id,
                    AgentEntityStateRecord.entity_id == node_id,
                    AgentEntityStateRecord.active == True,  # noqa: E712
                )
                .order_by(AgentEntityStateRecord.updated_at.desc())
                .first()
            )
        if record is None:
            return KnowledgeNodeResolution(found=False, node_type="entity_state", node_id=node_id, message="EntityState not found")
        return KnowledgeNodeResolution(
            found=True,
            node_type="entity_state",
            node_id=node_id,
            title=record.entity_name or record.entity_id,
            summary=_clean_text(record.notes or str(record.attributes_json or {}), 280),
            data={"id": record.id, "agent_id": record.agent_id, "entity_id": record.entity_id, "state_kind": record.state_kind, "entity_type": record.entity_type},
        )

    def _resolve_procedural_skill(self, agent_id: str, node_id: str) -> KnowledgeNodeResolution:
        record = None
        int_id = _try_int(node_id)
        if int_id is not None:
            record = self.db.get(AgentProceduralSkillRecord, int_id)
        if record is None:
            record = (
                self.db.query(AgentProceduralSkillRecord)
                .filter(
                    AgentProceduralSkillRecord.agent_id == agent_id,
                    AgentProceduralSkillRecord.skill_key == node_id,
                    AgentProceduralSkillRecord.active == True,  # noqa: E712
                )
                .one_or_none()
            )
        if record is None:
            return KnowledgeNodeResolution(found=False, node_type="procedural_skill", node_id=node_id, message="Procedural skill not found")
        return KnowledgeNodeResolution(
            found=True,
            node_type="procedural_skill",
            node_id=node_id,
            title=record.title or record.skill_key,
            summary=_clean_text(record.description or record.notes or record.skill_key, 280),
            data={"id": record.id, "agent_id": record.agent_id, "skill_key": record.skill_key, "skill_type": record.skill_type, "status": record.status, "priority": record.priority},
        )

    def _resolve_memory(self, agent_id: str, node_id: str) -> KnowledgeNodeResolution:
        int_id = _try_int(node_id)
        if int_id is None:
            return KnowledgeNodeResolution(found=False, node_type="memory", node_id=node_id, message="Memory id must be numeric")
        record = self.db.get(MemoryRecord, int_id)
        if record is None or getattr(record, "agent_id", None) != agent_id or not getattr(record, "active", True):
            return KnowledgeNodeResolution(found=False, node_type="memory", node_id=node_id, message="Memory not found")
        return KnowledgeNodeResolution(
            found=True,
            node_type="memory",
            node_id=node_id,
            title=f"Memory {record.id}",
            summary=_clean_text(record.content or "", 280),
            data={"id": record.id, "agent_id": record.agent_id, "memory_type": record.memory_type, "importance": record.importance},
        )

    def _resolve_agent(self, node_id: str) -> KnowledgeNodeResolution:
        record = self.db.get(AgentRecord, node_id)
        if record is None:
            return KnowledgeNodeResolution(found=False, node_type="agent", node_id=node_id, message="Agent not found")
        return KnowledgeNodeResolution(
            found=True,
            node_type="agent",
            node_id=node_id,
            title=record.name or record.id,
            summary=_clean_text(record.description or record.personality or "", 280),
            data={"id": record.id, "name": record.name},
        )


def reads_from_records(records: Iterable[KnowledgeRelationRecord]) -> list[KnowledgeRelationRead]:
    return [KnowledgeRelationRead.from_record(record) for record in records]
