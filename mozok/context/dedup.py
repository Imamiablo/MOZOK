from __future__ import annotations

import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable, Sequence

from mozok.db.models import MemoryRecord
from mozok.schemas.memory import MemorySearchResult


MemoryLike = MemoryRecord | MemorySearchResult


LEVEL_PRIORITY = {
    "core": 4,
    "semantic": 3,
    "episodic": 2,
    "raw": 1,
}

# Small language-aware stopword sets for cheap retrieval-time dedup.
# This is not meant to be full NLP. It only removes common function words so
# obvious duplicates compare more cleanly across the project languages we use
# most often: English, Ukrainian, and Russian.
EN_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "but", "by",
    "for", "from", "had", "has", "have", "he", "her", "his", "i", "in", "is",
    "it", "its", "me", "my", "of", "on", "or", "our", "she", "so", "that",
    "the", "their", "them", "there", "they", "this", "to", "was", "we", "were",
    "with", "you", "your",
}

UA_STOPWORDS = {
    "але", "або", "без", "бо", "була", "були", "було", "бути", "вам", "вас",
    "вже", "він", "вона", "вони", "воно", "для", "до", "його", "йому", "її",
    "із", "коли", "мене", "мені", "ми", "мій", "на", "над", "нам", "нас", "не",
    "нема", "ні", "про", "та", "так", "там", "ти", "то", "тут", "це", "цей",
    "ця", "цю", "що", "як", "які", "який",
}

RU_STOPWORDS = {
    "без", "был", "была", "были", "было", "быть", "вам", "вас", "все", "для",
    "его", "ему", "если", "есть", "или", "как", "когда", "мне", "мой", "мы",
    "на", "над", "нам", "нас", "не", "нет", "ни", "но", "она", "они", "оно",
    "он", "от", "по", "при", "про", "так", "там", "то", "тут", "ты", "это",
    "этот", "что", "я",
}

STOPWORDS = EN_STOPWORDS | UA_STOPWORDS | RU_STOPWORDS

NEGATION_TOKENS = {
    "not", "never", "no", "none", "cannot", "cant", "can't", "wont", "won't",
    "isnt", "isn't", "doesnt", "doesn't", "dont", "don't", "не", "ні", "ніколи",
    "нема", "немає", "нет", "никогда",
}

SUPERSEDES_HINTS = {
    "updated", "update", "replaces", "replaced", "corrected", "correction", "now",
    "anymore", "instead", "no longer", "оновлено", "замість", "більше не",
    "виправлено", "тепер", "обновлено", "вместо", "больше не", "теперь",
}


@dataclass(frozen=True)
class TextFingerprint:
    normalized_text: str
    tokens: frozenset[str]
    negation_tokens: frozenset[str]
    has_supersedes_hint: bool


def normalize_text(text: str) -> str:
    """Normalise memory text for conservative dedup comparisons."""

    clean = (text or "").lower()

    # Raw memories often have wrappers. Remove them so they can be compared
    # with later summaries more fairly.
    clean = re.sub(r"\b(user said|bot replied|assistant replied)\s*:\s*", "", clean)

    # Keep Latin/Cyrillic words, numbers, CJK blocks, spaces and hyphens.
    clean = re.sub(
        r"[^a-z0-9а-яіїєґё\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\-\s]",
        " ",
        clean,
        flags=re.IGNORECASE,
    )
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def language_aware_tokens(normalized_text: str) -> list[str]:
    """Return cheap tokens suitable for dedup across Latin/Cyrillic/CJK text."""

    tokens: list[str] = []
    for token in (normalized_text or "").split():
        token = token.strip("-_")
        if not token:
            continue

        if _contains_cjk(token):
            tokens.extend(_cjk_ngrams(token))
            continue

        if len(token) < 3:
            continue
        if token in STOPWORDS:
            continue
        tokens.append(token)
    return tokens


def fingerprint_text(text: str) -> TextFingerprint:
    normalized = normalize_text(text)
    token_list = language_aware_tokens(normalized)
    token_set = frozenset(token_list)
    negations = frozenset(token for token in token_set if token in NEGATION_TOKENS)
    supersedes_hint = any(hint in normalized for hint in SUPERSEDES_HINTS)
    return TextFingerprint(
        normalized_text=normalized,
        tokens=token_set,
        negation_tokens=negations,
        has_supersedes_hint=supersedes_hint,
    )


def sequence_similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def token_overlap(a_tokens: frozenset[str], b_tokens: frozenset[str]) -> float:
    if not a_tokens or not b_tokens:
        return 0.0
    smaller = min(len(a_tokens), len(b_tokens))
    return len(a_tokens & b_tokens) / max(1, smaller)


def cosine_similarity(vector_a: Sequence[float], vector_b: Sequence[float]) -> float:
    """Small dependency-free cosine helper for embedding-based audit tests."""

    if vector_a is None or vector_b is None:
        return 0.0

    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for a, b in zip(vector_a, vector_b):
        fa = float(a)
        fb = float(b)
        dot += fa * fb
        norm_a += fa * fa
        norm_b += fb * fb

    if norm_a <= 0 or norm_b <= 0:
        return 0.0
    value = dot / (math.sqrt(norm_a) * math.sqrt(norm_b))
    return max(-1.0, min(1.0, float(value)))


def memory_sort_key(memory: MemoryLike, source: str | None = None) -> tuple[int, int, float, int]:
    memory_type = source or str(getattr(memory, "memory_type", "") or "")
    return (
        LEVEL_PRIORITY.get(memory_type, 0),
        int(getattr(memory, "importance", 0) or 0),
        float(getattr(memory, "score", 0.0) or 0.0),
        int(getattr(memory, "id", 0) or 0),
    )


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff]", text or ""))


def _cjk_ngrams(token: str) -> list[str]:
    chars = [char for char in token if char.strip()]
    if len(chars) <= 2:
        return ["".join(chars)] if chars else []
    return ["".join(chars[i : i + 2]) for i in range(len(chars) - 1)]


@dataclass(frozen=True)
class DedupCandidate:
    """Normalized wrapper around a memory object used during prompt dedup."""

    memory: MemoryLike
    source: str
    memory_id: int
    content: str
    fingerprint: TextFingerprint
    priority: int
    importance: int
    score: float

    @property
    def normalized_text(self) -> str:
        return self.fingerprint.normalized_text

    @property
    def token_set(self) -> frozenset[str]:
        return self.fingerprint.tokens


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
    relation_type: str = "duplicate_of"
    embedding_similarity: float | None = None

    def to_dict(self) -> dict:
        return {
            "removed_id": self.removed_id,
            "removed_source": self.removed_source,
            "kept_id": self.kept_id,
            "kept_source": self.kept_source,
            "similarity": self.similarity,
            "token_overlap": self.token_overlap,
            "embedding_similarity": self.embedding_similarity,
            "relation_type": self.relation_type,
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

    Real database deduplication/merging should be done through the read-only
    Dedup V2 audit endpoint and future explicit apply/relation workflows.
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

            existing, similarity, overlap, relation_type = match
            removed.append(
                DedupRemovedMemory(
                    removed_id=candidate.memory_id,
                    removed_source=candidate.source,
                    kept_id=existing.memory_id,
                    kept_source=existing.source,
                    similarity=round(similarity, 4),
                    token_overlap=round(overlap, 4),
                    relation_type=relation_type,
                    reason=(
                        f"{relation_type}_context_memory; hidden from this prompt only; "
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
            fingerprint = fingerprint_text(content)

            if not fingerprint.normalized_text or not fingerprint.tokens:
                continue

            wrapped.append(
                DedupCandidate(
                    memory=memory,
                    source=source,
                    memory_id=memory_id,
                    content=content,
                    fingerprint=fingerprint,
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
        return memory_sort_key(memory, source)

    def _find_duplicate(
        self,
        candidate: DedupCandidate,
        kept: list[DedupCandidate],
    ) -> tuple[DedupCandidate, float, float, str] | None:
        for existing in kept:
            if candidate.memory_id and candidate.memory_id == existing.memory_id:
                return existing, 1.0, 1.0, "duplicate_of"

            similarity = sequence_similarity(candidate.normalized_text, existing.normalized_text)
            overlap = token_overlap(candidate.token_set, existing.token_set)
            relation_type = self._relation_type_for_pair(candidate, existing, similarity=similarity, overlap=overlap)

            # In context prompt dedup we hide only duplicates/superseded variants.
            # Similar/contradicting memories are left visible so the LLM can see
            # nuance or conflict; the audit endpoint reports them for review.
            if relation_type in {"duplicate_of", "supersedes"}:
                return existing, similarity, overlap, relation_type

        return None

    def _relation_type_for_pair(
        self,
        a: DedupCandidate,
        b: DedupCandidate,
        similarity: float,
        overlap: float,
    ) -> str | None:
        """Conservative near-duplicate check based on words + character similarity."""

        # Very short memories are risky to dedup automatically.
        if len(a.token_set) < 4 or len(b.token_set) < 4:
            return None

        if _looks_contradictory(a.fingerprint, b.fingerprint, overlap):
            return "contradicts"

        if overlap >= self.token_overlap_threshold:
            # Avoid collapsing a specific event into a broad general rule unless
            # the text is also fairly close. This keeps cases like
            # "Maria usually steals food" and "Maria stole steak today" separate.
            shared = len(a.token_set & b.token_set)
            if similarity >= 0.72 or shared >= 8:
                if a.fingerprint.has_supersedes_hint or b.fingerprint.has_supersedes_hint:
                    return "supersedes"
                return "duplicate_of"

        if similarity >= self.similarity_threshold:
            return "duplicate_of"

        return None

    # Backwards-compatible private helpers used by older tests/extensions.
    def _sequence_similarity(self, a: str, b: str) -> float:
        return sequence_similarity(a, b)

    def _token_overlap(self, a_tokens: frozenset[str], b_tokens: frozenset[str]) -> float:
        return token_overlap(a_tokens, b_tokens)

    def _normalize_text(self, text: str) -> str:
        return normalize_text(text)

    def _tokens(self, normalized_text: str) -> list[str]:
        return language_aware_tokens(normalized_text)


def _looks_contradictory(a: TextFingerprint, b: TextFingerprint, overlap: float) -> bool:
    if overlap < 0.62:
        return False
    return bool(a.negation_tokens) != bool(b.negation_tokens)
