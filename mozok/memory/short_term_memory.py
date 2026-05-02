from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import RLock
from typing import Literal


Role = Literal["user", "assistant", "system"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ShortTermMessage:
    """One message kept in the bot's working memory.

    This is intentionally not a SQL model.
    Short-term memory is the bot's RAM/context buffer: useful right now,
    disposable later, and safe to clear at the end of a session.
    """

    role: Role
    content: str
    created_at: datetime = field(default_factory=utc_now)


class ShortTermMemoryStore:
    """In-process working memory for recent chat turns.

    Long-term memory lives in PostgreSQL + FAISS.
    Short-term memory lives only in Python RAM so the bot can keep continuity
    during the current conversation without polluting long-term memory search.

    MVP limitation:
    - this memory is per Python process;
    - it is lost when the API restarts;
    - if you later run multiple API workers, use Redis or another shared cache.
    """

    def __init__(self, max_messages_per_session: int = 40):
        self.max_messages_per_session = max(2, int(max_messages_per_session))
        self._messages: dict[tuple[str, str], deque[ShortTermMessage]] = {}
        self._lock = RLock()

    def add_message(self, agent_id: str, session_id: str, role: Role, content: str) -> None:
        """Append one message to an agent/session working-memory buffer."""

        clean_agent_id = self._clean_key(agent_id)
        clean_session_id = self._clean_key(session_id or "default")
        clean_content = (content or "").strip()
        if not clean_content:
            return

        key = (clean_agent_id, clean_session_id)
        with self._lock:
            if key not in self._messages:
                self._messages[key] = deque(maxlen=self.max_messages_per_session)
            self._messages[key].append(ShortTermMessage(role=role, content=clean_content))

    def get_messages(self, agent_id: str, session_id: str, limit: int = 20) -> list[ShortTermMessage]:
        """Return the most recent messages for this agent/session."""

        clean_agent_id = self._clean_key(agent_id)
        clean_session_id = self._clean_key(session_id or "default")
        safe_limit = max(0, min(int(limit), self.max_messages_per_session))
        if safe_limit == 0:
            return []

        key = (clean_agent_id, clean_session_id)
        with self._lock:
            messages = list(self._messages.get(key, []))
        return messages[-safe_limit:]

    def clear_session(self, agent_id: str, session_id: str) -> int:
        """Forget short-term memory for one session and return removed count."""

        key = (self._clean_key(agent_id), self._clean_key(session_id or "default"))
        with self._lock:
            messages = self._messages.pop(key, deque())
        return len(messages)

    def clear_agent(self, agent_id: str) -> int:
        """Forget short-term memory for all sessions of one agent."""

        clean_agent_id = self._clean_key(agent_id)
        removed = 0
        with self._lock:
            keys_to_remove = [key for key in self._messages if key[0] == clean_agent_id]
            for key in keys_to_remove:
                removed += len(self._messages.pop(key, deque()))
        return removed

    def format_for_prompt(
        self,
        agent_id: str,
        session_id: str,
        limit: int = 20,
        max_chars_per_message: int = 700,
    ) -> str:
        """Format recent messages as a compact prompt block."""

        messages = self.get_messages(agent_id=agent_id, session_id=session_id, limit=limit)
        if not messages:
            return "No recent short-term conversation."

        lines: list[str] = []
        for message in messages:
            content = message.content.replace("\n", " ").strip()
            if len(content) > max_chars_per_message:
                content = content[: max_chars_per_message - 3] + "..."
            lines.append(f"- {message.role}: {content}")
        return "\n".join(lines)

    def _clean_key(self, value: str) -> str:
        return (value or "default").strip() or "default"


# A simple singleton is enough for the first version of the API.
# Later, replace this object with a Redis-backed implementation without changing BotCore.
SHORT_TERM_MEMORY = ShortTermMemoryStore(max_messages_per_session=40)
