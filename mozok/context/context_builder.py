from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from mozok.db.models import AgentRecord, MemoryRecord
from mozok.context.dedup import ContextMemoryDeduplicator, DedupRemovedMemory
from mozok.context.token_budget import ContextBudgeter, ContextBudgetPolicy, ContextBudgetReport
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
            raw_memories=deduped.raw_memories,
            dedup_removed_memories=deduped.removed,
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