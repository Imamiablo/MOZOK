from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable

from mozok.db.models import MemoryRecord
from mozok.schemas.memory import MemorySearchResult


MemoryLike = MemoryRecord | MemorySearchResult


LEVEL_PRIORITY = {
    "core": 4,
    "semantic": 3,
    "episodic": 2,
    "raw": 1,
}

# Small English stopword list for cheap prompt-time dedup.
# This is not meant to be a universal NLP system. It only removes common
# function words so obvious duplicates compare more cleanly.
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by",
    "for", "from", "had", "has", "have", "he", "her", "his", "i", "in", "is",
    "it", "its", "me", "my", "of", "on", "or", "our", "she", "so", "that",
    "the", "their", "them", "there", "they", "this", "to", "was", "we", "were",
    "with", "you", "your",
}


@dataclass(frozen=True)
class DedupCandidate:
    """Normalized wrapper around a memory object used during prompt dedup."""

    memory: MemoryLike
    source: str
    memory_id: int
    content: str
    normalized_text: str
    token_set: frozenset[str]
    priority: int
    importance: int
    score: float


@dataclass(frozen=True)
class DedupRemovedMemory:
    """Debug record explaining why one memory was hidden from this prompt."""

    removed_id: int
    removed_source: str
    kept_id: int
    kept_source: str
    similarity: float
    token_overlap: float
    reason: str

    def to_dict(self) -> dict:
        return {
            "removed_id": self.removed_id,
            "removed_source": self.removed_source,
            "kept_id": self.kept_id,
            "kept_source": self.kept_source,
            "similarity": self.similarity,
            "token_overlap": self.token_overlap,
            "reason": self.reason,
        }


@dataclass
class DedupResult:
    """Result of safe retrieval-time deduplication.

    This does not modify SQL/FAISS. It only tells ContextBuilder which memories
    should be included in the current prompt.
    """

    core_memories: list[MemoryRecord]
    semantic_memories: list[MemorySearchResult]
    episodic_memories: list[MemorySearchResult]
    raw_memories: list[MemorySearchResult]
    removed: list[DedupRemovedMemory]

    @property
    def removed_count(self) -> int:
        return len(self.removed)

    @property
    def removed_memory_ids(self) -> list[int]:
        return [item.removed_id for item in self.removed]


class ContextMemoryDeduplicator:
    """Remove near-duplicate memories from a single LLM context package.

    This is intentionally conservative and safe:
    - it does not delete, archive, or modify memories in the database;
    - it only removes near-duplicates from the prompt for this one LLM turn;
    - higher-level memory wins over lower-level memory:
      core > semantic > episodic > raw;
    - for the same level, higher importance wins, then higher retrieval score,
      then the newer/larger ID wins as a simple tie-breaker.

    Real database deduplication/merging should be a later maintenance/audit step.
    """

    def __init__(
        self,
        similarity_threshold: float = 0.86,
        token_overlap_threshold: float = 0.82,
    ):
        self.similarity_threshold = float(similarity_threshold)
        self.token_overlap_threshold = float(token_overlap_threshold)

    def deduplicate(
        self,
        core_memories: list[MemoryRecord],
        semantic_memories: list[MemorySearchResult],
        episodic_memories: list[MemorySearchResult],
        raw_memories: list[MemorySearchResult],
    ) -> DedupResult:
        """Return memory lists with near-duplicates removed for prompt use only."""

        candidates: list[DedupCandidate] = []
        candidates.extend(self._wrap_many(core_memories, source="core"))
        candidates.extend(self._wrap_many(semantic_memories, source="semantic"))
        candidates.extend(self._wrap_many(episodic_memories, source="episodic"))
        candidates.extend(self._wrap_many(raw_memories, source="raw"))

        # Best candidates are considered first, so weaker duplicates are skipped.
        candidates.sort(key=self._candidate_sort_key, reverse=True)

        kept: list[DedupCandidate] = []
        removed: list[DedupRemovedMemory] = []

        for candidate in candidates:
            match = self._find_duplicate(candidate, kept)
            if match is None:
                kept.append(candidate)
                continue

            existing, similarity, token_overlap = match
            removed.append(
                DedupRemovedMemory(
                    removed_id=candidate.memory_id,
                    removed_source=candidate.source,
                    kept_id=existing.memory_id,
                    kept_source=existing.source,
                    similarity=round(similarity, 4),
                    token_overlap=round(token_overlap, 4),
                    reason=(
                        "near_duplicate_context_memory; hidden from this prompt only; "
                        "database memory was not modified"
                    ),
                )
            )

        kept_by_source: dict[str, list[MemoryLike]] = {
            "core": [],
            "semantic": [],
            "episodic": [],
            "raw": [],
        }
        for candidate in kept:
            kept_by_source[candidate.source].append(candidate.memory)

        # Keep each bucket easy to read: strongest first.
        for source, memories in kept_by_source.items():
            memories.sort(
                key=lambda memory: self._memory_sort_key(memory, source),
                reverse=True,
            )

        return DedupResult(
            core_memories=list(kept_by_source["core"]),  # type: ignore[list-item]
            semantic_memories=list(kept_by_source["semantic"]),  # type: ignore[list-item]
            episodic_memories=list(kept_by_source["episodic"]),  # type: ignore[list-item]
            raw_memories=list(kept_by_source["raw"]),  # type: ignore[list-item]
            removed=removed,
        )

    def _wrap_many(self, memories: Iterable[MemoryLike], source: str) -> list[DedupCandidate]:
        wrapped: list[DedupCandidate] = []
        for memory in memories:
            content = str(getattr(memory, "content", "") or "").strip()
            if not content:
                continue

            memory_id = int(getattr(memory, "id", 0) or 0)
            normalized_text = self._normalize_text(content)
            token_set = frozenset(self._tokens(normalized_text))

            if not normalized_text or not token_set:
                continue

            wrapped.append(
                DedupCandidate(
                    memory=memory,
                    source=source,
                    memory_id=memory_id,
                    content=content,
                    normalized_text=normalized_text,
                    token_set=token_set,
                    priority=LEVEL_PRIORITY.get(source, 0),
                    importance=int(getattr(memory, "importance", 0) or 0),
                    score=float(getattr(memory, "score", 0.0) or 0.0),
                )
            )
        return wrapped

    def _candidate_sort_key(self, candidate: DedupCandidate) -> tuple[int, int, float, int, int]:
        return (
            candidate.priority,
            candidate.importance,
            candidate.score,
            len(candidate.token_set),
            candidate.memory_id,
        )

    def _memory_sort_key(self, memory: MemoryLike, source: str) -> tuple[int, int, float, int]:
        return (
            LEVEL_PRIORITY.get(source, 0),
            int(getattr(memory, "importance", 0) or 0),
            float(getattr(memory, "score", 0.0) or 0.0),
            int(getattr(memory, "id", 0) or 0),
        )

    def _find_duplicate(
        self,
        candidate: DedupCandidate,
        kept: list[DedupCandidate],
    ) -> tuple[DedupCandidate, float, float] | None:
        for existing in kept:
            if candidate.memory_id and candidate.memory_id == existing.memory_id:
                return existing, 1.0, 1.0

            similarity = self._sequence_similarity(candidate.normalized_text, existing.normalized_text)
            overlap = self._token_overlap(candidate.token_set, existing.token_set)

            if self._is_near_duplicate(candidate, existing, similarity=similarity, overlap=overlap):
                return existing, similarity, overlap

        return None

    def _is_near_duplicate(
        self,
        a: DedupCandidate,
        b: DedupCandidate,
        similarity: float,
        overlap: float,
    ) -> bool:
        """Conservative near-duplicate check based on words + character similarity."""

        # Very short memories are risky to dedup automatically.
        if len(a.token_set) < 4 or len(b.token_set) < 4:
            return False

        # Token containment catches paraphrases like:
        # "practical beginner-friendly explanations" vs
        # "beginner friendly practical explanations".
        if overlap >= self.token_overlap_threshold:
            # Avoid collapsing a specific event into a broad general rule unless
            # the text is also fairly close. This keeps cases like
            # "Maria usually steals food" and "Maria stole steak today" separate.
            shared = len(a.token_set & b.token_set)
            if similarity >= 0.72 or shared >= 8:
                return True

        return similarity >= self.similarity_threshold

    def _sequence_similarity(self, a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()

    def _token_overlap(self, a_tokens: frozenset[str], b_tokens: frozenset[str]) -> float:
        if not a_tokens or not b_tokens:
            return 0.0
        smaller = min(len(a_tokens), len(b_tokens))
        return len(a_tokens & b_tokens) / max(1, smaller)

    def _normalize_text(self, text: str) -> str:
        clean = text.lower()

        # Raw memories often have wrappers. Remove them so they can be compared
        # with later summaries more fairly.
        clean = re.sub(r"\b(user said|bot replied|assistant replied)\s*:\s*", "", clean)

        clean = re.sub(r"[^a-z0-9а-яіїєґё\-\s]", " ", clean, flags=re.IGNORECASE)
        clean = re.sub(r"\s+", " ", clean).strip()
        return clean

    def _tokens(self, normalized_text: str) -> list[str]:
        tokens = []
        for token in normalized_text.split():
            token = token.strip("-_")
            if len(token) < 3:
                continue
            if token in STOPWORDS:
                continue
            tokens.append(token)
        return tokens
