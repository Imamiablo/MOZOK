from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from mozok.db.models import AgentRecord, MemoryRecord
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
        )

        episodic_memories = self.memory_service.search(
            agent_id=agent_id,
            query=user_message,
            limit=episodic_limit,
            memory_type="episodic",
        )

        raw_memories: list[MemorySearchResult] = []
        if raw_limit > 0:
            raw_memories = self.memory_service.search(
                agent_id=agent_id,
                query=user_message,
                limit=raw_limit,
                memory_type="raw",
            )

        return ContextPackage(
            agent_id=agent_id,
            session_id=session_id,
            system_prompt=agent.system_prompt or "",
            agent_name=agent.name or agent.id,
            agent_description=agent.description or "",
            agent_personality=agent.personality or "",
            current_user_message=user_message,
            short_term_messages=short_term_messages,
            core_memories=core_memories,
            semantic_memories=semantic_memories,
            episodic_memories=episodic_memories,
            raw_memories=raw_memories,
        )

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