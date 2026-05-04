from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from mozok.db.models import AgentRecord, MemoryRecord
from mozok.context.dedup import ContextMemoryDeduplicator, DedupRemovedMemory
from mozok.context.token_budget import ContextBudgeter, ContextBudgetPolicy, ContextBudgetReport, estimate_tokens
from mozok.memory.policy import MEMORY_LEVEL_CORE
from mozok.memory.service import MemoryService
from mozok.memory.short_term_memory import SHORT_TERM_MEMORY, ShortTermMessage
from mozok.schemas.memory import MemorySearchResult


@dataclass
class ContextPackage:
    """Structured context prepared for the LLM.

    The important idea:
    BotCore should not manually decide which memories go into the prompt.
    BotCore asks ContextBuilder for a ready context package.
    """

    agent_id: str
    session_id: str
    system_prompt: str
    agent_name: str
    agent_description: str
    agent_personality: str
    current_user_message: str

    short_term_messages: list[ShortTermMessage] = field(default_factory=list)
    core_memories: list[MemoryRecord] = field(default_factory=list)
    semantic_memories: list[MemorySearchResult] = field(default_factory=list)
    episodic_memories: list[MemorySearchResult] = field(default_factory=list)
    raw_memories: list[MemorySearchResult] = field(default_factory=list)
    dedup_removed_memories: list[DedupRemovedMemory] = field(default_factory=list)
    context_budget: ContextBudgetReport | None = None

    # Debug-only snapshots used to explain the context assembly pipeline.
    # These are copies of earlier stages so later budget trimming can mutate the
    # final prompt lists without hiding what happened before.
    retrieved_short_term_messages: list[ShortTermMessage] = field(default_factory=list)
    retrieved_core_memories: list[MemoryRecord] = field(default_factory=list)
    retrieved_semantic_memories: list[MemorySearchResult] = field(default_factory=list)
    retrieved_episodic_memories: list[MemorySearchResult] = field(default_factory=list)
    retrieved_raw_memories: list[MemorySearchResult] = field(default_factory=list)

    post_dedup_short_term_messages: list[ShortTermMessage] = field(default_factory=list)
    post_dedup_core_memories: list[MemoryRecord] = field(default_factory=list)
    post_dedup_semantic_memories: list[MemorySearchResult] = field(default_factory=list)
    post_dedup_episodic_memories: list[MemorySearchResult] = field(default_factory=list)
    post_dedup_raw_memories: list[MemorySearchResult] = field(default_factory=list)

    def used_memory_ids(self) -> list[int]:
        """Return IDs of long-term memories included in this context."""

        ids: list[int] = []

        ids.extend(memory.id for memory in self.core_memories)
        ids.extend(memory.id for memory in self.semantic_memories)
        ids.extend(memory.id for memory in self.episodic_memories)
        ids.extend(memory.id for memory in self.raw_memories)

        # Keep order but remove duplicates.
        return list(dict.fromkeys(ids))

    def used_short_term_count(self) -> int:
        return len(self.short_term_messages)

    def dedup_removed_count(self) -> int:
        return len(self.dedup_removed_memories)

    def dedup_removed_memory_ids(self) -> list[int]:
        return [item.removed_id for item in self.dedup_removed_memories]

    def pipeline_steps(self) -> list[dict]:
        """Explain how the final prompt context was assembled.

        This is mostly for /debug/context and a future UI popup. It separates
        the stages that were previously mixed together in one response:
        retrieval -> deduplication -> token-budget trimming -> final prompt.
        """

        final_prompt = self.to_system_prompt()
        final_estimated_tokens = estimate_tokens(final_prompt)

        retrieved_counts = self._stage_counts(
            short_term_messages=self.retrieved_short_term_messages,
            core_memories=self.retrieved_core_memories,
            semantic_memories=self.retrieved_semantic_memories,
            episodic_memories=self.retrieved_episodic_memories,
            raw_memories=self.retrieved_raw_memories,
        )
        post_dedup_counts = self._stage_counts(
            short_term_messages=self.post_dedup_short_term_messages,
            core_memories=self.post_dedup_core_memories,
            semantic_memories=self.post_dedup_semantic_memories,
            episodic_memories=self.post_dedup_episodic_memories,
            raw_memories=self.post_dedup_raw_memories,
        )
        final_counts = self._stage_counts(
            short_term_messages=self.short_term_messages,
            core_memories=self.core_memories,
            semantic_memories=self.semantic_memories,
            episodic_memories=self.episodic_memories,
            raw_memories=self.raw_memories,
        )

        budget_report = self.context_budget.to_dict() if self.context_budget else None
        budget_trimmed_items = budget_report.get("trimmed_items", []) if budget_report else []
        over_budget_after_trimming = bool(budget_report.get("over_budget_after_trimming", False)) if budget_report else False

        return [
            {
                "step": "retrieved",
                "label": "Retrieved candidate context",
                "description": "ContextBuilder fetched short-term messages, core memories, and relevant long-term memories before dedup or budget trimming.",
                "status": "ok",
                "counts": retrieved_counts,
                "memory_ids_by_source": self._memory_ids_by_source(
                    self.retrieved_core_memories,
                    self.retrieved_semantic_memories,
                    self.retrieved_episodic_memories,
                    self.retrieved_raw_memories,
                ),
            },
            {
                "step": "deduped",
                "label": "Applied safe context dedup",
                "description": "Near-duplicate memories were hidden from this prompt only. The database and FAISS index were not modified.",
                "status": "changed" if self.dedup_removed_memories else "ok",
                "input_counts": retrieved_counts,
                "output_counts": post_dedup_counts,
                "removed_count": self.dedup_removed_count(),
                "removed_memory_ids": self.dedup_removed_memory_ids(),
                "removed_details": [item.to_dict() for item in self.dedup_removed_memories],
            },
            {
                "step": "budget_trimmed",
                "label": "Applied token budget",
                "description": "The post-dedup context was trimmed if the estimated prompt exceeded the configured budget.",
                "status": (
                    "over_budget"
                    if over_budget_after_trimming
                    else "changed" if budget_trimmed_items
                    else "ok"
                ),
                "input_counts": post_dedup_counts,
                "output_counts": final_counts,
                "budget": budget_report,
            },
            {
                "step": "final_prompt",
                "label": "Final prompt context",
                "description": "These are the exact context sections that remain in the final prompt sent to the LLM.",
                "status": "over_budget" if over_budget_after_trimming else "ok",
                "counts": final_counts,
                "used_memory_ids": self.used_memory_ids(),
                "estimated_prompt_tokens": final_estimated_tokens,
                "prompt_characters": len(final_prompt),
                "notes": self._final_prompt_notes(final_counts, over_budget_after_trimming),
            },
        ]

    def _stage_counts(
        self,
        short_term_messages: list[ShortTermMessage],
        core_memories: list[MemoryRecord],
        semantic_memories: list[MemorySearchResult],
        episodic_memories: list[MemorySearchResult],
        raw_memories: list[MemorySearchResult],
    ) -> dict:
        return {
            "short_term_messages": len(short_term_messages),
            "core_memories": len(core_memories),
            "semantic_memories": len(semantic_memories),
            "episodic_memories": len(episodic_memories),
            "raw_memories": len(raw_memories),
            "total_long_term_memories": (
                len(core_memories)
                + len(semantic_memories)
                + len(episodic_memories)
                + len(raw_memories)
            ),
        }

    def _memory_ids_by_source(
        self,
        core_memories: list[MemoryRecord],
        semantic_memories: list[MemorySearchResult],
        episodic_memories: list[MemorySearchResult],
        raw_memories: list[MemorySearchResult],
    ) -> dict:
        return {
            "core": self._memory_ids(core_memories),
            "semantic": self._memory_ids(semantic_memories),
            "episodic": self._memory_ids(episodic_memories),
            "raw": self._memory_ids(raw_memories),
        }

    def _memory_ids(self, memories: list) -> list[int]:
        ids: list[int] = []
        for memory in memories:
            memory_id = getattr(memory, "id", None)
            if memory_id is not None:
                ids.append(int(memory_id))
        return ids

    def _final_prompt_notes(self, final_counts: dict, over_budget_after_trimming: bool) -> list[str]:
        notes: list[str] = []
        if final_counts.get("total_long_term_memories", 0) == 0:
            notes.append("No long-term memories remain in the final prompt.")
        if over_budget_after_trimming:
            notes.append(
                "The prompt is still over budget after trimming all allowed context items. "
                "This usually means the base prompt, agent profile, user message, or response guidance is too large for the configured budget."
            )
        return notes

    def to_debug_dict(self, include_full_prompt: bool = True, prompt_preview_chars: int = 2000) -> dict:
        """Return a serializable view of the exact context assembled for this turn.

        This is intended for debug UIs/popups. It does not call the LLM.
        """

        full_prompt = self.to_system_prompt()
        safe_preview_chars = max(0, int(prompt_preview_chars))

        return {
            "agent_id": self.agent_id,
            "session_id": self.session_id,
            "current_user_message": self.current_user_message,
            "used_memory_ids": self.used_memory_ids(),
            "used_short_term_messages_count": self.used_short_term_count(),
            "dedup_removed_memories_count": self.dedup_removed_count(),
            "dedup_removed_memory_ids": self.dedup_removed_memory_ids(),
            "dedup_removed_details": [item.to_dict() for item in self.dedup_removed_memories],
            "context_budget": self.context_budget.to_dict() if self.context_budget else None,
            "pipeline_steps": self.pipeline_steps(),
            "sections": {
                "agent_profile": {
                    "name": self.agent_name,
                    "description": self.agent_description,
                    "personality": self.agent_personality,
                    "system_prompt": self.system_prompt,
                },
                "short_term_messages": [
                    {
                        "role": message.role,
                        "content": message.content,
                        "created_at": message.created_at.isoformat(),
                    }
                    for message in self.short_term_messages
                ],
                "core_memories": [self._memory_to_debug_dict(memory, source="core") for memory in self.core_memories],
                "semantic_memories": [self._memory_to_debug_dict(memory, source="semantic") for memory in self.semantic_memories],
                "episodic_memories": [self._memory_to_debug_dict(memory, source="episodic") for memory in self.episodic_memories],
                "raw_memories": [self._memory_to_debug_dict(memory, source="raw") for memory in self.raw_memories],
            },
            "prompt_preview": full_prompt[:safe_preview_chars] if safe_preview_chars else "",
            "full_prompt": full_prompt if include_full_prompt else None,
        }

    def _memory_to_debug_dict(self, memory, source: str) -> dict:
        """Convert a memory object into a JSON-safe debug dictionary.

        Important SQLAlchemy foot-gun:
        Declarative models can expose a `.metadata` attribute from SQLAlchemy
        itself. That object is not JSON serializable and can make FastAPI's
        jsonable_encoder recurse until it crashes.

        Our actual memory metadata lives in `metadata_json` on SQL records and
        in `metadata` on Pydantic search results, so we read those carefully and
        only return plain dictionaries.
        """

        if hasattr(memory, "metadata_json"):
            metadata = getattr(memory, "metadata_json", None)
        else:
            metadata = getattr(memory, "metadata", None)

        if not isinstance(metadata, dict):
            metadata = {}

        return {
            "id": getattr(memory, "id", None),
            "source": source,
            "memory_type": getattr(memory, "memory_type", None),
            "importance": getattr(memory, "importance", None),
            "score": getattr(memory, "score", None),
            "content": getattr(memory, "content", ""),
            "metadata": metadata,
        }

    def to_system_prompt(self) -> str:
        """Convert structured context into a plain system prompt for the LLM."""

        sections: list[str] = []

        if self.system_prompt:
            sections.append(
                "System instructions:\n"
                f"{self.system_prompt}"
            )

        profile_lines = [
            f"Name: {self.agent_name}",
            f"Description: {self.agent_description}",
            f"Personality: {self.agent_personality}",
        ]
        profile_text = "\n".join(line for line in profile_lines if line and not line.endswith(": "))
        if profile_text:
            sections.append(f"Agent profile:\n{profile_text}")

        if self.core_memories:
            sections.append(
                "Core/profile memories. Treat these as stable identity or high-priority facts:\n"
                + "\n".join(
                    f"- {memory.content}"
                    for memory in self.core_memories
                    if memory.content
                )
            )

        if self.short_term_messages:
            sections.append(
                "Recent conversation / short-term working memory:\n"
                + "\n".join(
                    f"- {message.role}: {self._compact(message.content)}"
                    for message in self.short_term_messages
                    if message.content
                )
            )
        else:
            sections.append("Recent conversation / short-term working memory:\nNo recent messages.")

        if self.semantic_memories:
            sections.append(
                "Relevant semantic memories. These are facts, preferences, summaries, or stable knowledge:\n"
                + "\n".join(
                    f"- {memory.content}"
                    for memory in self.semantic_memories
                    if memory.content
                )
            )

        if self.episodic_memories:
            sections.append(
                "Relevant episodic memories. These are past events or experiences:\n"
                + "\n".join(
                    f"- {memory.content}"
                    for memory in self.episodic_memories
                    if memory.content
                )
            )

        if self.raw_memories:
            sections.append(
                "Relevant raw memories. These may be noisy and should be treated carefully:\n"
                + "\n".join(
                    f"- {memory.content}"
                    for memory in self.raw_memories
                    if memory.content
                )
            )

        sections.append(
            "Current user message:\n"
            f"{self.current_user_message}"
        )

        sections.append(
            "Response guidance:\n"
            "- Use memories only when they are relevant.\n"
            "- Do not claim to remember something unless it appears in the provided context.\n"
            "- If memories conflict, prefer core/profile memories, then semantic memories, then episodic memories, then raw memories.\n"
            "- Keep the response natural and useful."
        )

        return "\n\n---\n\n".join(section for section in sections if section.strip())

    def _compact(self, text: str, max_chars: int = 700) -> str:
        clean = (text or "").replace("\n", " ").strip()
        if len(clean) <= max_chars:
            return clean
        return clean[: max_chars - 3] + "..."


class ContextBuilder:
    """Builds the context that will be sent to the LLM before each response."""

    def __init__(self, db: Session, memory_service: MemoryService):
        self.db = db
        self.memory_service = memory_service
        self.deduplicator = ContextMemoryDeduplicator()

    def build(
        self,
        agent: AgentRecord,
        user_message: str,
        session_id: str = "default",
        short_term_limit: int = 20,
        core_limit: int = 10,
        semantic_limit: int = 6,
        episodic_limit: int = 4,
        raw_limit: int = 0,
        update_memory_access: bool = True,
        enforce_token_budget: bool = True,
        max_prompt_tokens: int = 6000,
        reserved_response_tokens: int = 1000,
        allow_core_trimming: bool = False,
    ) -> ContextPackage:
        """Collect profile + short-term + long-term memory for one LLM turn."""

        agent_id = agent.id

        short_term_messages = SHORT_TERM_MEMORY.get_messages(
            agent_id=agent_id,
            session_id=session_id,
            limit=short_term_limit,
        )

        core_memories = self._get_core_memories(
            agent_id=agent_id,
            limit=core_limit,
        )

        semantic_memories = self.memory_service.search(
            agent_id=agent_id,
            query=user_message,
            limit=semantic_limit,
            memory_type="semantic",
            update_access=update_memory_access,
        )

        episodic_memories = self.memory_service.search(
            agent_id=agent_id,
            query=user_message,
            limit=episodic_limit,
            memory_type="episodic",
            update_access=update_memory_access,
        )

        raw_memories: list[MemorySearchResult] = []
        if raw_limit > 0:
            raw_memories = self.memory_service.search(
                agent_id=agent_id,
                query=user_message,
                limit=raw_limit,
                memory_type="raw",
                update_access=update_memory_access,
            )

        deduped = self.deduplicator.deduplicate(
            core_memories=core_memories,
            semantic_memories=semantic_memories,
            episodic_memories=episodic_memories,
            raw_memories=raw_memories,
        )

        context_package = ContextPackage(
            agent_id=agent_id,
            session_id=session_id,
            system_prompt=agent.system_prompt or "",
            agent_name=agent.name or agent.id,
            agent_description=agent.description or "",
            agent_personality=agent.personality or "",
            current_user_message=user_message,
            short_term_messages=short_term_messages,
            core_memories=deduped.core_memories,
            semantic_memories=deduped.semantic_memories,
            episodic_memories=deduped.episodic_memories,
            raw_memories=list(deduped.raw_memories),
            dedup_removed_memories=list(deduped.removed),
            retrieved_short_term_messages=list(short_term_messages),
            retrieved_core_memories=list(core_memories),
            retrieved_semantic_memories=list(semantic_memories),
            retrieved_episodic_memories=list(episodic_memories),
            retrieved_raw_memories=list(raw_memories),
            post_dedup_short_term_messages=list(short_term_messages),
            post_dedup_core_memories=list(deduped.core_memories),
            post_dedup_semantic_memories=list(deduped.semantic_memories),
            post_dedup_episodic_memories=list(deduped.episodic_memories),
            post_dedup_raw_memories=list(deduped.raw_memories),
        )

        budget_policy = ContextBudgetPolicy(
            enforce=enforce_token_budget,
            max_prompt_tokens=max_prompt_tokens,
            reserved_response_tokens=reserved_response_tokens,
            allow_core_trimming=allow_core_trimming,
        )
        context_package.context_budget = ContextBudgeter(budget_policy).apply(context_package)

        return context_package

    def _get_core_memories(self, agent_id: str, limit: int) -> list[MemoryRecord]:
        """Core memories are usually always relevant, so fetch them directly from SQL."""

        safe_limit = max(0, int(limit))
        if safe_limit == 0:
            return []

        return (
            self.db.query(MemoryRecord)
            .filter(
                MemoryRecord.agent_id == agent_id,
                MemoryRecord.active == True,  # noqa: E712
                MemoryRecord.memory_type == MEMORY_LEVEL_CORE,
            )
            .order_by(MemoryRecord.importance.desc(), MemoryRecord.created_at.desc())
            .limit(safe_limit)
            .all()
        )