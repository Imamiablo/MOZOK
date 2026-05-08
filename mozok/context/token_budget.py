from __future__ import annotations

from dataclasses import dataclass, field
from math import ceil
from typing import Any


CHARS_PER_TOKEN_ESTIMATE = 4
MIN_PROMPT_TARGET_TOKENS = 80


def estimate_tokens(text: str | None) -> int:
    """Return a cheap token estimate for early context budgeting.

    This is intentionally lightweight. It does not use a model-specific tokenizer.
    For English-like text, 1 token is often roughly 3-5 characters, so 4 chars per
    token is a practical MVP estimate.
    """

    clean = text or ""
    if not clean:
        return 0
    return max(1, ceil(len(clean) / CHARS_PER_TOKEN_ESTIMATE))


def compact_preview(text: str | None, max_chars: int = 180) -> str:
    clean = (text or "").replace("\n", " ").strip()
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 3] + "..."


@dataclass
class ContextBudgetPolicy:
    """Controls how much context may be placed into the LLM prompt.

    max_prompt_tokens is treated as the total model-side budget for prompt +
    reserved answer. available_prompt_tokens is calculated as:

        max_prompt_tokens - reserved_response_tokens

    Example:
        max_prompt_tokens=6000 and reserved_response_tokens=1000 means Mozok
        should try to keep the assembled prompt under about 5000 tokens.
    """

    enforce: bool = True
    max_prompt_tokens: int = 6000
    reserved_response_tokens: int = 1000
    allow_core_trimming: bool = False

    @property
    def available_prompt_tokens(self) -> int:
        return max(
            MIN_PROMPT_TARGET_TOKENS,
            int(self.max_prompt_tokens) - int(self.reserved_response_tokens),
        )


@dataclass
class TrimmedContextItem:
    source: str
    memory_id: int | None
    estimated_tokens: int
    reason: str
    content_preview: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "memory_id": self.memory_id,
            "estimated_tokens": self.estimated_tokens,
            "reason": self.reason,
            "content_preview": self.content_preview,
        }


@dataclass
class ContextBudgetReport:
    enabled: bool
    max_prompt_tokens: int
    reserved_response_tokens: int
    available_prompt_tokens: int
    estimated_prompt_tokens_before: int
    estimated_prompt_tokens_after: int
    trimmed_items: list[TrimmedContextItem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def trimmed_count(self) -> int:
        return len(self.trimmed_items)

    @property
    def over_budget_after_trimming(self) -> bool:
        return self.estimated_prompt_tokens_after > self.available_prompt_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "max_prompt_tokens": self.max_prompt_tokens,
            "reserved_response_tokens": self.reserved_response_tokens,
            "available_prompt_tokens": self.available_prompt_tokens,
            "estimated_prompt_tokens_before": self.estimated_prompt_tokens_before,
            "estimated_prompt_tokens_after": self.estimated_prompt_tokens_after,
            "trimmed_count": self.trimmed_count,
            "trimmed_items": [item.to_dict() for item in self.trimmed_items],
            "over_budget_after_trimming": self.over_budget_after_trimming,
            "notes": self.notes,
        }


class ContextBudgeter:
    """Applies a simple prompt budget to a ContextPackage.

    This is a safe MVP budgeter:
    - it trims only the already-selected prompt context;
    - it does not delete or modify database memories;
    - it prefers dropping noisy/low-priority context first;
    - it returns a debug report explaining what happened.

    Trim order:
        raw -> episodic -> semantic -> lorebook -> entity-state -> short-term oldest messages -> core only if allowed
    """

    def __init__(self, policy: ContextBudgetPolicy | None = None):
        self.policy = policy or ContextBudgetPolicy()

    def apply(self, context_package: Any) -> ContextBudgetReport:
        before = estimate_tokens(context_package.to_system_prompt())

        report = ContextBudgetReport(
            enabled=bool(self.policy.enforce),
            max_prompt_tokens=int(self.policy.max_prompt_tokens),
            reserved_response_tokens=int(self.policy.reserved_response_tokens),
            available_prompt_tokens=int(self.policy.available_prompt_tokens),
            estimated_prompt_tokens_before=before,
            estimated_prompt_tokens_after=before,
        )

        if not self.policy.enforce:
            report.notes.append("Context budget enforcement is disabled for this request.")
            return report

        if before <= self.policy.available_prompt_tokens:
            report.notes.append("Context was already within the configured token budget.")
            return report

        trim_plan = [
            ("raw", "raw_memories", "context_budget_exceeded_trim_raw_first"),
            ("episodic", "episodic_memories", "context_budget_exceeded_trim_weak_episodic"),
            ("semantic", "semantic_memories", "context_budget_exceeded_trim_weak_semantic"),
            ("lorebook", "lorebook_items", "context_budget_exceeded_trim_lorebook_after_memories"),
            ("entity_state", "entity_state_items", "context_budget_exceeded_trim_entity_state_after_lorebook"),
            ("short_term", "short_term_messages", "context_budget_exceeded_trim_oldest_short_term"),
        ]

        if self.policy.allow_core_trimming:
            trim_plan.append(("core", "core_memories", "context_budget_exceeded_trim_core_last_resort"))
        else:
            report.notes.append("Core/profile memories are protected from token-budget trimming.")

        for source, attr_name, reason in trim_plan:
            items = getattr(context_package, attr_name, None)
            if not isinstance(items, list):
                continue

            while items and estimate_tokens(context_package.to_system_prompt()) > self.policy.available_prompt_tokens:
                # For short-term memory, keep the most recent messages and remove the oldest first.
                # For retrieved memories, lists are expected to be ranked best-first, so remove the tail.
                if source == "short_term":
                    removed = items.pop(0)
                else:
                    removed = items.pop()

                content = self._content_for_trimmed_item(removed)
                report.trimmed_items.append(
                    TrimmedContextItem(
                        source=source,
                        memory_id=self._id_for_trimmed_item(removed),
                        estimated_tokens=estimate_tokens(content),
                        reason=reason,
                        content_preview=compact_preview(content),
                    )
                )

            if estimate_tokens(context_package.to_system_prompt()) <= self.policy.available_prompt_tokens:
                break

        after = estimate_tokens(context_package.to_system_prompt())
        report.estimated_prompt_tokens_after = after

        if report.trimmed_count == 0:
            report.notes.append("Prompt exceeded budget, but there were no trim-safe context items available.")
        elif after <= self.policy.available_prompt_tokens:
            report.notes.append("Context was trimmed to fit the configured token budget.")
        else:
            report.notes.append("Context is still over budget after all allowed trimming steps.")

        return report


    def _id_for_trimmed_item(self, item: Any) -> int | None:
        if getattr(item, "id", None) is not None:
            return getattr(item, "id", None)
        if getattr(item, "lorebook_entry_id", None) is not None:
            return getattr(item, "lorebook_entry_id", None)
        return None

    def _content_for_trimmed_item(self, item: Any) -> str:
        content = getattr(item, "content", None)
        if content:
            return str(content)

        # EntityStateRead objects do not have a single content field; use a compact
        # stable representation so trimming reports remain useful.
        entity_name = getattr(item, "entity_name", "") or getattr(item, "entity_id", "")
        state_kind = getattr(item, "state_kind", "entity_state")
        attributes = getattr(item, "attributes", None)
        if attributes is None:
            attributes = getattr(item, "attributes_json", None)
        notes = getattr(item, "notes", "")
        return f"{entity_name} | kind={state_kind} | attributes={attributes or {}} | notes={notes or ''}"
