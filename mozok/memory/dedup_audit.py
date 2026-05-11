from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from mozok.context.dedup import (
    LEVEL_PRIORITY,
    TextFingerprint,
    cosine_similarity,
    fingerprint_text,
    sequence_similarity,
    token_overlap,
)
from mozok.db.models import MemoryRecord
from mozok.embeddings.base import EmbeddingService
from mozok.memory.policy import normalize_memory_type
from mozok.schemas.memory import (
    MemoryDedupAuditCandidate,
    MemoryDedupAuditMemoryPreview,
    MemoryDedupAuditRequest,
    MemoryDedupAuditResponse,
    MemoryDedupRelationSuggestion,
)


DEDUP_RELATION_DUPLICATE = "duplicate_of"
DEDUP_RELATION_SIMILAR = "similar_to"
DEDUP_RELATION_SUPERSEDES = "supersedes"
DEDUP_RELATION_CONTRADICTS = "contradicts"


class MemoryDedupAuditService:
    """Read-only Dedup V2 audit for long-term memories.

    The service deliberately returns suggestions only. It does not delete,
    merge, archive, modify metadata, touch FAISS, or create graph relations.
    Suggested relation payloads are included so a future explicit apply workflow
    can create ``duplicate_of``, ``similar_to``, ``supersedes`` or
    ``contradicts`` edges after review.
    """

    def __init__(self, db: Session, embedding_service: EmbeddingService | None = None):
        self.db = db
        self.embedding_service = embedding_service

    def audit(self, agent_id: str, request: MemoryDedupAuditRequest | None = None) -> MemoryDedupAuditResponse:
        data = request or MemoryDedupAuditRequest()
        records = self._load_memories(agent_id=agent_id, request=data)
        fingerprints = {int(record.id): fingerprint_text(record.content or "") for record in records}
        embeddings = self._embed_records(records, enabled=data.include_embedding_similarity)

        compared_pairs = 0
        candidates: list[MemoryDedupAuditCandidate] = []

        for left_index, left in enumerate(records):
            for right in records[left_index + 1 :]:
                compared_pairs += 1
                candidate = self._candidate_for_pair(
                    agent_id=agent_id,
                    world_id=data.world_id,
                    left=left,
                    right=right,
                    left_fp=fingerprints[int(left.id)],
                    right_fp=fingerprints[int(right.id)],
                    left_embedding=embeddings.get(int(left.id)),
                    right_embedding=embeddings.get(int(right.id)),
                    request=data,
                )
                if candidate is not None:
                    candidates.append(candidate)

        candidates.sort(key=lambda item: (item.confidence, item.embedding_similarity or 0.0, item.text_similarity), reverse=True)
        candidates = candidates[: data.max_pairs]
        summary = Counter(item.suggested_relation_type for item in candidates)

        notes = [
            "Dedup V2 audit is read-only: no SQL memories, FAISS vectors, metadata, or knowledge relations were modified.",
            "Candidates are relation suggestions, not automatic deletion instructions.",
            "Never hard-delete automatically; review or convert suggestions into explicit graph relations first.",
        ]
        if data.include_embedding_similarity and self.embedding_service is None:
            notes.append("Embedding similarity was requested but no embedding service was available; text/token signals were used only.")

        return MemoryDedupAuditResponse(
            agent_id=agent_id,
            world_id=data.world_id,
            dry_run=True,
            scanned_memories=len(records),
            compared_pairs=compared_pairs,
            candidates_count=len(candidates),
            candidates=candidates,
            summary=dict(summary),
            notes=notes,
        )

    def _load_memories(self, agent_id: str, request: MemoryDedupAuditRequest) -> list[MemoryRecord]:
        query = self.db.query(MemoryRecord).filter(MemoryRecord.agent_id == agent_id)
        if not request.include_inactive:
            query = query.filter(MemoryRecord.active == True)  # noqa: E712

        if request.memory_types:
            normalised_types = [normalize_memory_type(item) for item in request.memory_types]
            query = query.filter(MemoryRecord.memory_type.in_(normalised_types))

        return (
            query.order_by(
                MemoryRecord.memory_type.asc(),
                MemoryRecord.importance.desc(),
                MemoryRecord.updated_at.desc(),
                MemoryRecord.id.desc(),
            )
            .limit(max(2, min(int(request.limit), 1000)))
            .all()
        )

    def _embed_records(self, records: list[MemoryRecord], enabled: bool) -> dict[int, Any]:
        if not enabled or self.embedding_service is None:
            return {}

        vectors: dict[int, Any] = {}
        for record in records:
            try:
                vector = self.embedding_service.embed_text(record.content or "")
                if hasattr(vector, "tolist"):
                    vector = vector.tolist()
                vectors[int(record.id)] = vector
            except Exception:
                # Audit should stay useful even if a local embedding backend fails.
                continue
        return vectors

    def _candidate_for_pair(
        self,
        *,
        agent_id: str,
        world_id: str,
        left: MemoryRecord,
        right: MemoryRecord,
        left_fp: TextFingerprint,
        right_fp: TextFingerprint,
        left_embedding: Any | None,
        right_embedding: Any | None,
        request: MemoryDedupAuditRequest,
    ) -> MemoryDedupAuditCandidate | None:
        if not left_fp.tokens or not right_fp.tokens:
            return None

        text_sim = sequence_similarity(left_fp.normalized_text, right_fp.normalized_text)
        overlap = token_overlap(left_fp.tokens, right_fp.tokens)
        embedding_sim: float | None = None
        if left_embedding is not None and right_embedding is not None:
            embedding_sim = cosine_similarity(left_embedding, right_embedding)

        relation_type, reasons = self._classify_pair(
            left=left,
            right=right,
            left_fp=left_fp,
            right_fp=right_fp,
            text_similarity=text_sim,
            overlap=overlap,
            embedding_similarity=embedding_sim,
            request=request,
        )
        if relation_type is None:
            return None

        confidence = self._confidence(
            relation_type=relation_type,
            text_similarity=text_sim,
            overlap=overlap,
            embedding_similarity=embedding_sim,
        )
        if confidence < request.min_confidence:
            return None

        primary, secondary = self._primary_secondary(left, right, left_fp, right_fp, relation_type)
        relation_suggestion = None
        if request.include_relation_suggestions:
            relation_suggestion = self._relation_suggestion(
                agent_id=agent_id,
                world_id=world_id,
                relation_type=relation_type,
                primary=primary,
                secondary=secondary,
                confidence=confidence,
                text_similarity=text_sim,
                overlap=overlap,
                embedding_similarity=embedding_sim,
            )

        return MemoryDedupAuditCandidate(
            primary_memory=self._preview(primary),
            secondary_memory=self._preview(secondary),
            suggested_relation_type=relation_type,
            confidence=round(confidence, 4),
            text_similarity=round(text_sim, 4),
            token_overlap=round(overlap, 4),
            embedding_similarity=round(embedding_sim, 4) if embedding_sim is not None else None,
            reasons=reasons,
            safe_action="review_only",
            would_modify=False,
            would_delete=False,
            relation_suggestion=relation_suggestion,
        )

    def _classify_pair(
        self,
        *,
        left: MemoryRecord,
        right: MemoryRecord,
        left_fp: TextFingerprint,
        right_fp: TextFingerprint,
        text_similarity: float,
        overlap: float,
        embedding_similarity: float | None,
        request: MemoryDedupAuditRequest,
    ) -> tuple[str | None, list[str]]:
        reasons: list[str] = []
        shared_token_count = len(left_fp.tokens & right_fp.tokens)
        embedding_hit = embedding_similarity is not None and embedding_similarity >= request.min_embedding_similarity
        text_hit = text_similarity >= request.min_text_similarity
        overlap_hit = overlap >= request.min_token_overlap

        if self._looks_contradictory(left_fp, right_fp, overlap):
            if overlap_hit or text_similarity >= 0.70 or embedding_hit:
                reasons.append("high shared topic overlap with one-sided negation marker")
                if embedding_hit:
                    reasons.append("embedding similarity supports same-topic conflict")
                return DEDUP_RELATION_CONTRADICTS, reasons

        if self._looks_superseding(left, right, left_fp, right_fp, text_similarity, overlap, embedding_hit):
            reasons.append("one memory appears to update or replace the other")
            if overlap_hit:
                reasons.append("strong token overlap")
            if embedding_hit:
                reasons.append("high embedding similarity")
            return DEDUP_RELATION_SUPERSEDES, reasons

        if text_hit:
            reasons.append("high normalised text similarity")
        if overlap_hit and (text_similarity >= 0.72 or shared_token_count >= 8):
            reasons.append("strong token containment / overlap")
        if embedding_hit and (overlap >= 0.48 or text_similarity >= 0.58):
            reasons.append("high embedding similarity with matching text/topic signal")

        duplicate_signals = 0
        if text_hit:
            duplicate_signals += 1
        if overlap_hit and (text_similarity >= 0.72 or shared_token_count >= 8):
            duplicate_signals += 1
        if embedding_hit and (overlap >= 0.58 or text_similarity >= 0.66):
            duplicate_signals += 1

        if duplicate_signals >= 2 or (text_similarity >= 0.92 and overlap >= 0.60):
            return DEDUP_RELATION_DUPLICATE, reasons or ["multiple duplicate signals"]

        if embedding_hit or text_similarity >= 0.74 or overlap >= 0.62:
            if embedding_hit:
                reasons.append("embedding similarity suggests related meaning")
            if text_similarity >= 0.74:
                reasons.append("moderate normalised text similarity")
            if overlap >= 0.62:
                reasons.append("moderate token overlap")
            return DEDUP_RELATION_SIMILAR, reasons or ["similar topic"]

        return None, []

    def _looks_contradictory(self, left_fp: TextFingerprint, right_fp: TextFingerprint, overlap: float) -> bool:
        if overlap < 0.58:
            return False
        return bool(left_fp.negation_tokens) != bool(right_fp.negation_tokens)

    def _looks_superseding(
        self,
        left: MemoryRecord,
        right: MemoryRecord,
        left_fp: TextFingerprint,
        right_fp: TextFingerprint,
        text_similarity: float,
        overlap: float,
        embedding_hit: bool,
    ) -> bool:
        if not (left_fp.has_supersedes_hint or right_fp.has_supersedes_hint):
            return False
        if text_similarity >= 0.70 or overlap >= 0.68 or embedding_hit:
            return True
        return False

    def _confidence(
        self,
        *,
        relation_type: str,
        text_similarity: float,
        overlap: float,
        embedding_similarity: float | None,
    ) -> float:
        embedding_component = embedding_similarity if embedding_similarity is not None else 0.0
        if relation_type == DEDUP_RELATION_CONTRADICTS:
            return max(0.55, (overlap * 0.45) + (text_similarity * 0.25) + (max(0.0, embedding_component) * 0.30))
        if relation_type == DEDUP_RELATION_SUPERSEDES:
            return max(0.58, (overlap * 0.35) + (text_similarity * 0.35) + (max(0.0, embedding_component) * 0.30))
        if relation_type == DEDUP_RELATION_DUPLICATE:
            return max(0.60, (overlap * 0.35) + (text_similarity * 0.35) + (max(0.0, embedding_component) * 0.30))
        return max(0.50, (overlap * 0.25) + (text_similarity * 0.25) + (max(0.0, embedding_component) * 0.50))

    def _primary_secondary(
        self,
        left: MemoryRecord,
        right: MemoryRecord,
        left_fp: TextFingerprint,
        right_fp: TextFingerprint,
        relation_type: str,
    ) -> tuple[MemoryRecord, MemoryRecord]:
        if relation_type == DEDUP_RELATION_SUPERSEDES:
            if left_fp.has_supersedes_hint and not right_fp.has_supersedes_hint:
                return left, right
            if right_fp.has_supersedes_hint and not left_fp.has_supersedes_hint:
                return right, left
            return self._newer_first(left, right)

        # For duplicate/similar/contradict edges, primary is the memory that
        # should be reviewed as the stronger/reference item.
        return self._stronger_first(left, right)

    def _newer_first(self, left: MemoryRecord, right: MemoryRecord) -> tuple[MemoryRecord, MemoryRecord]:
        left_dt = self._datetime_sort_value(getattr(left, "updated_at", None), getattr(left, "id", 0))
        right_dt = self._datetime_sort_value(getattr(right, "updated_at", None), getattr(right, "id", 0))
        return (left, right) if left_dt >= right_dt else (right, left)

    def _stronger_first(self, left: MemoryRecord, right: MemoryRecord) -> tuple[MemoryRecord, MemoryRecord]:
        left_key = (
            LEVEL_PRIORITY.get(left.memory_type, 0),
            int(left.importance or 0),
            int(left.id or 0),
        )
        right_key = (
            LEVEL_PRIORITY.get(right.memory_type, 0),
            int(right.importance or 0),
            int(right.id or 0),
        )
        return (left, right) if left_key >= right_key else (right, left)

    def _datetime_sort_value(self, value: datetime | None, fallback_id: int) -> tuple[float, int]:
        if value is None:
            return (0.0, int(fallback_id or 0))
        try:
            return (float(value.timestamp()), int(fallback_id or 0))
        except Exception:
            return (0.0, int(fallback_id or 0))

    def _relation_suggestion(
        self,
        *,
        agent_id: str,
        world_id: str,
        relation_type: str,
        primary: MemoryRecord,
        secondary: MemoryRecord,
        confidence: float,
        text_similarity: float,
        overlap: float,
        embedding_similarity: float | None,
    ) -> MemoryDedupRelationSuggestion:
        if relation_type == DEDUP_RELATION_DUPLICATE:
            source = secondary
            target = primary
            description = "Suggested duplicate memory. Keep both until reviewed; this relation only documents the duplicate signal."
        elif relation_type == DEDUP_RELATION_SUPERSEDES:
            source = primary
            target = secondary
            description = "Suggested superseding memory. Newer/stronger memory appears to update or replace the older one."
        elif relation_type == DEDUP_RELATION_CONTRADICTS:
            source = primary
            target = secondary
            description = "Suggested contradiction. Memories appear to discuss the same topic with conflicting polarity."
        else:
            source = secondary
            target = primary
            description = "Suggested similar memory. Not a duplicate; useful for graph navigation and review."

        evidence = {
            "text_similarity": round(text_similarity, 4),
            "token_overlap": round(overlap, 4),
            "embedding_similarity": round(embedding_similarity, 4) if embedding_similarity is not None else None,
            "audit_only": True,
        }
        return MemoryDedupRelationSuggestion(
            agent_id=agent_id,
            world_id=world_id,
            source_id=str(source.id),
            relation_type=relation_type,
            target_id=str(target.id),
            strength=round(max(0.1, min(1.0, confidence)), 4),
            confidence=round(max(0.0, min(1.0, confidence)), 4),
            description=description,
            evidence=evidence,
            metadata={
                "created_by": "dedup_v2_audit",
                "safe_action": "review_only",
                "would_delete": False,
            },
            validate_nodes=False,
        )

    def _preview(self, record: MemoryRecord) -> MemoryDedupAuditMemoryPreview:
        return MemoryDedupAuditMemoryPreview(
            id=int(record.id),
            memory_type=record.memory_type,
            importance=int(record.importance or 0),
            content_preview=self._compact(record.content or ""),
        )

    def _compact(self, text: str, max_chars: int = 180) -> str:
        clean = " ".join((text or "").split())
        if len(clean) <= max_chars:
            return clean
        return clean[: max_chars - 3] + "..."
