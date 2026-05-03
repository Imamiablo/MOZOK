from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from statistics import mean
from typing import Any, Protocol

from mozok.db.models import MemoryRecord


class ChatLikeClient(Protocol):
    """Small protocol so the summarizer is not tied to one LLM wrapper."""

    model: str

    def chat(self, system_prompt: str, user_message: str, temperature: float = 0.7) -> str:
        ...


@dataclass(frozen=True)
class MemorySummaryDraft:
    """Prepared summary content before it is saved as a MemoryRecord."""

    content: str
    method: str
    model: str | None = None
    error: str | None = None


class MemorySummarizer:
    """Turns raw/episodic memories into cleaner semantic summary text.

    The important design choice is safety: maintenance must not crash just
    because Ollama is closed, the selected model fails, or the LLM returns an
    empty answer. In those cases we fall back to a deterministic summary.
    """

    def __init__(self, llm_client: ChatLikeClient | None = None):
        self.llm_client = llm_client

    def summarize(
        self,
        *,
        agent_id: str,
        source_records: list[MemoryRecord],
        trigger: str,
        policy: dict[str, Any] | None = None,
    ) -> MemorySummaryDraft:
        """Create a semantic summary draft from source memory records."""

        policy = dict(policy or {})
        summarizer_policy = dict(policy.get("summarizer") or {})

        enabled = bool(summarizer_policy.get("enabled", True))
        fallback_enabled = bool(summarizer_policy.get("fallback_to_deterministic", True))
        max_source_memories = int(summarizer_policy.get("max_source_memories_for_llm", 30))
        max_chars_per_source = int(summarizer_policy.get("max_chars_per_source_memory", 600))
        max_summary_chars = int(summarizer_policy.get("max_summary_chars", 1800))
        temperature = float(summarizer_policy.get("temperature", 0.2))

        source_records = [record for record in source_records if record is not None]

        if enabled and self.llm_client is not None and source_records:
            try:
                content = self._summarize_with_llm(
                    agent_id=agent_id,
                    source_records=source_records[:max_source_memories],
                    trigger=trigger,
                    max_chars_per_source=max_chars_per_source,
                    max_summary_chars=max_summary_chars,
                    temperature=temperature,
                )
                if content:
                    return MemorySummaryDraft(
                        content=content,
                        method="llm",
                        model=getattr(self.llm_client, "model", None),
                        error=None,
                    )
            except Exception as exc:  # noqa: BLE001 - maintenance must be resilient
                if fallback_enabled:
                    fallback = self.deterministic_summary(
                        agent_id=agent_id,
                        source_records=source_records,
                        trigger=trigger,
                    )
                    return MemorySummaryDraft(
                        content=fallback,
                        method="deterministic_fallback",
                        model=getattr(self.llm_client, "model", None),
                        error=f"{type(exc).__name__}: {exc}",
                    )
                raise

        if not fallback_enabled and enabled:
            return MemorySummaryDraft(
                content="",
                method="disabled_no_fallback",
                model=getattr(self.llm_client, "model", None) if self.llm_client else None,
                error="LLM summarizer was unavailable and deterministic fallback is disabled.",
            )

        return MemorySummaryDraft(
            content=self.deterministic_summary(
                agent_id=agent_id,
                source_records=source_records,
                trigger=trigger,
            ),
            method="deterministic",
            model=None,
            error=None,
        )

    def _summarize_with_llm(
        self,
        *,
        agent_id: str,
        source_records: list[MemoryRecord],
        trigger: str,
        max_chars_per_source: int,
        max_summary_chars: int,
        temperature: float,
    ) -> str:
        if self.llm_client is None:
            return ""

        source_text = self._format_source_records(
            source_records=source_records,
            max_chars_per_source=max_chars_per_source,
        )

        system_prompt = (
            "You are Mozok's memory consolidation module. "
            "Your job is to convert noisy raw memories into useful long-term semantic memory.\n\n"
            "Rules:\n"
            "- Do not invent facts. Only summarize what is supported by the source memories.\n"
            "- Prefer stable facts, user preferences, decisions, unresolved tasks, and repeated patterns.\n"
            "- Ignore trivial greetings, filler, and temporary wording unless it matters.\n"
            "- If there are contradictions, mention uncertainty instead of choosing blindly.\n"
            "- Write compact memory notes, not a chat reply.\n"
            "- Use the dominant language of the source memories.\n"
            "- Do not include IDs unless they are meaningful to remember.\n"
            "- Output plain text only. No markdown code fences.\n"
        )
        user_message = (
            f"Agent ID: {agent_id}\n"
            f"Maintenance trigger: {trigger}\n"
            f"Source memory count: {len(source_records)}\n\n"
            "Create a concise semantic memory summary from these source memories.\n"
            "Recommended format:\n"
            "- Stable facts/preferences/decisions.\n"
            "- Important events if any.\n"
            "- Open tasks/questions if any.\n\n"
            f"Keep the whole summary under about {max_summary_chars} characters.\n\n"
            "SOURCE MEMORIES:\n"
            f"{source_text}"
        )

        response = self.llm_client.chat(
            system_prompt=system_prompt,
            user_message=user_message,
            temperature=temperature,
        )
        return self._clean_llm_summary(response, max_summary_chars=max_summary_chars)

    def deterministic_summary(
        self,
        *,
        agent_id: str,
        source_records: list[MemoryRecord],
        trigger: str,
    ) -> str:
        """Old safe summary style, kept as fallback."""

        now = datetime.now(timezone.utc)
        source_records = [record for record in source_records if record is not None]
        if not source_records:
            return f"Memory maintenance summary created at {now.isoformat()} with no source memories."

        start_at = min((record.created_at for record in source_records if record.created_at), default=now)
        end_at = max((record.created_at for record in source_records if record.created_at), default=now)

        lines: list[str] = []
        for record in source_records[:20]:
            trimmed = " ".join((record.content or "").split())[:260]
            lines.append(
                f"- ({record.memory_type}, id={record.id}, importance={record.importance}) {trimmed}"
            )

        return (
            f"Memory consolidation summary for agent '{agent_id}'.\n"
            f"Trigger: {trigger}.\n"
            f"Covered source memories: {len(source_records)}.\n"
            f"Period: {start_at.isoformat()} to {end_at.isoformat()}.\n"
            "Source notes:\n"
            + "\n".join(lines)
        )

    def _format_source_records(
        self,
        *,
        source_records: list[MemoryRecord],
        max_chars_per_source: int,
    ) -> str:
        lines: list[str] = []
        safe_max = max(100, int(max_chars_per_source))

        for record in source_records:
            content = " ".join((record.content or "").split())
            if len(content) > safe_max:
                content = content[: safe_max - 3] + "..."

            created_at = record.created_at.isoformat() if record.created_at else "unknown-time"
            metadata = dict(record.metadata_json or {})
            speaker = metadata.get("speaker") or metadata.get("role") or "unknown"
            session_id = metadata.get("session_id") or "unknown-session"

            lines.append(
                f"[{record.id}] type={record.memory_type}; "
                f"importance={record.importance}; emotion={record.emotional_weight}; "
                f"speaker={speaker}; session={session_id}; created_at={created_at}\n"
                f"{content}"
            )

        return "\n\n".join(lines)

    def _clean_llm_summary(self, text: str | None, max_summary_chars: int) -> str:
        clean = (text or "").strip()
        if not clean:
            return ""

        # Some local models wrap everything in code fences. Strip the wrapper.
        if clean.startswith("```"):
            clean = clean.strip("`").strip()
            if clean.lower().startswith("text"):
                clean = clean[4:].strip()

        clean = clean.replace("\r\n", "\n").strip()
        safe_max = max(300, int(max_summary_chars))
        if len(clean) > safe_max:
            clean = clean[: safe_max - 3].rstrip() + "..."
        return clean


# Small helper used by MemoryService for summary metadata.
def estimate_summary_importance(source_records: list[MemoryRecord]) -> int:
    source_records = [record for record in source_records if record is not None]
    if not source_records:
        return 4
    return max(4, min(8, round(mean([record.importance for record in source_records]))))


def estimate_summary_emotional_weight(source_records: list[MemoryRecord]) -> float:
    source_records = [record for record in source_records if record is not None]
    if not source_records:
        return 0.0
    return float(mean([record.emotional_weight for record in source_records]))
