from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timezone
from math import ceil
from typing import Any

from mozok.memory.short_term_memory import ShortTermMessage


CHARS_PER_TOKEN_ESTIMATE = 4.0
MIN_PROMPT_TARGET_TOKENS = 80
MIN_SECTION_BUDGET_TOKENS = 12
DEFAULT_COMPRESSION_RATIO = 0.45


MODEL_TOKEN_PROFILES: dict[str, float] = {
    "generic": 4.0,
    "openai": 3.7,
    "gpt": 3.7,
    "qwen": 3.4,
    "qwen3": 3.4,
    "llama": 3.8,
    "mistral": 3.8,
    "gemma": 3.7,
    "japanese": 2.2,
    "cjk": 2.2,
}

# Soft defaults. They intentionally do not spend 100% of the available prompt
# budget because the base system prompt, user message, section headings, and
# response guidance also need room.
DEFAULT_SECTION_BUDGET_SHARES: dict[str, float] = {
    "goals": 0.06,
    "procedural_skills": 0.07,
    "entity_states": 0.07,
    "lorebook": 0.12,
    "knowledge_relations": 0.06,
    "core": 0.11,
    "short_term": 0.12,
    "semantic": 0.11,
    "episodic": 0.08,
    "raw": 0.03,
}


@dataclass(frozen=True)
class SectionDefinition:
    name: str
    attr_name: str
    source: str
    trim_from_front: bool = False
    trim_protected: bool = False


SECTION_DEFINITIONS: tuple[SectionDefinition, ...] = (
    SectionDefinition("goals", "goal_items", "goal"),
    SectionDefinition("procedural_skills", "procedural_skill_items", "procedural_skill"),
    SectionDefinition("entity_states", "entity_state_items", "entity_state"),
    SectionDefinition("lorebook", "lorebook_items", "lorebook"),
    SectionDefinition("knowledge_relations", "knowledge_relation_items", "knowledge_relation"),
    SectionDefinition("core", "core_memories", "core", trim_protected=True),
    SectionDefinition("short_term", "short_term_messages", "short_term", trim_from_front=True),
    SectionDefinition("semantic", "semantic_memories", "semantic"),
    SectionDefinition("episodic", "episodic_memories", "episodic"),
    SectionDefinition("raw", "raw_memories", "raw"),
)

SECTION_BY_NAME = {definition.name: definition for definition in SECTION_DEFINITIONS}


def chars_per_token_for_model(model_name: str | None = None) -> float:
    """Return a lightweight token-estimation profile for a model name.

    This is still an approximation, not a real tokenizer. The point is to make
    the estimate less naive than a single global constant, especially for local
    models and CJK-heavy text.
    """

    clean_name = (model_name or "generic").strip().lower()
    if not clean_name:
        return CHARS_PER_TOKEN_ESTIMATE

    if clean_name in MODEL_TOKEN_PROFILES:
        return MODEL_TOKEN_PROFILES[clean_name]

    for key, chars_per_token in MODEL_TOKEN_PROFILES.items():
        if key != "generic" and key in clean_name:
            return chars_per_token

    return CHARS_PER_TOKEN_ESTIMATE


def estimate_tokens(
    text: str | None,
    model_name: str | None = None,
    chars_per_token: float | None = None,
) -> int:
    """Return a cheap model-aware token estimate for context budgeting."""

    clean = text or ""
    if not clean:
        return 0
    divisor = float(chars_per_token or chars_per_token_for_model(model_name))
    if divisor <= 0:
        divisor = CHARS_PER_TOKEN_ESTIMATE
    return max(1, ceil(len(clean) / divisor))


def compact_preview(text: str | None, max_chars: int = 180) -> str:
    clean = (text or "").replace("\n", " ").strip()
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 3] + "..."


def context_item_key(source: str, item: Any) -> str:
    """Stable enough key for request-local compressed prompt text.

    We deliberately do not mutate SQLAlchemy records just to shorten a prompt.
    The ContextPackage stores compressed text in a side-table keyed by object
    identity for the current request only.
    """

    return f"{source}:{id(item)}"


def compress_text(
    text: str | None,
    target_tokens: int,
    model_name: str | None = None,
    chars_per_token: float | None = None,
) -> str:
    """Deterministically shorten text while preserving the beginning and end."""

    clean = " ".join((text or "").split())
    if not clean:
        return ""

    current_tokens = estimate_tokens(clean, model_name=model_name, chars_per_token=chars_per_token)
    safe_target_tokens = max(8, int(target_tokens))
    if current_tokens <= safe_target_tokens:
        return clean

    cpt = float(chars_per_token or chars_per_token_for_model(model_name))
    target_chars = max(40, int(safe_target_tokens * cpt))
    marker = " ... [compressed for context budget] ... "
    if len(clean) <= target_chars:
        return clean

    available_chars = max(20, target_chars - len(marker))
    front_chars = max(12, int(available_chars * 0.68))
    back_chars = max(8, available_chars - front_chars)
    if front_chars + back_chars + len(marker) >= len(clean):
        return clean
    return clean[:front_chars].rstrip() + marker + clean[-back_chars:].lstrip()


@dataclass
class ContextBudgetPolicy:
    """Controls how much context may be placed into the LLM prompt.

    max_prompt_tokens is treated as the total model-side budget for prompt +
    reserved answer. available_prompt_tokens is calculated as:

        max_prompt_tokens - reserved_response_tokens

    V2 additions:
    - model_name changes the cheap token-estimation ratio;
    - section_budget_tokens lets callers set per-section soft caps;
    - compression can shorten selected prompt text before dropping items;
    - short-term summarisation keeps old chat continuity as one compact note;
    - budget-aware graph expansion can cap relation fan-out before prompt build.
    """

    enforce: bool = True
    max_prompt_tokens: int = 6000
    reserved_response_tokens: int = 1000
    allow_core_trimming: bool = False
    model_name: str = "generic"
    section_budget_tokens: dict[str, int] = field(default_factory=dict)
    compression_enabled: bool = True
    short_term_summarization_enabled: bool = True
    budget_aware_graph_expansion: bool = True

    @property
    def chars_per_token(self) -> float:
        return chars_per_token_for_model(self.model_name)

    @property
    def available_prompt_tokens(self) -> int:
        return max(
            MIN_PROMPT_TARGET_TOKENS,
            int(self.max_prompt_tokens) - int(self.reserved_response_tokens),
        )

    def section_budget_for(self, section_name: str) -> int | None:
        explicit = self.section_budget_tokens or {}
        if section_name in explicit:
            value = int(explicit[section_name])
            return None if value <= 0 else value

        share = DEFAULT_SECTION_BUDGET_SHARES.get(section_name)
        if share is None:
            return None
        return max(MIN_SECTION_BUDGET_TOKENS, int(self.available_prompt_tokens * share))


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
class CompressedContextItem:
    source: str
    memory_id: int | None
    estimated_tokens_before: int
    estimated_tokens_after: int
    reason: str
    content_preview_before: str
    content_preview_after: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "memory_id": self.memory_id,
            "estimated_tokens_before": self.estimated_tokens_before,
            "estimated_tokens_after": self.estimated_tokens_after,
            "tokens_saved": max(0, self.estimated_tokens_before - self.estimated_tokens_after),
            "reason": self.reason,
            "content_preview_before": self.content_preview_before,
            "content_preview_after": self.content_preview_after,
        }


@dataclass
class ShortTermSummaryReport:
    original_message_count: int
    kept_recent_message_count: int
    estimated_tokens_before: int
    estimated_tokens_after: int
    summary_preview: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_message_count": self.original_message_count,
            "kept_recent_message_count": self.kept_recent_message_count,
            "summarised_message_count": max(0, self.original_message_count - self.kept_recent_message_count),
            "estimated_tokens_before": self.estimated_tokens_before,
            "estimated_tokens_after": self.estimated_tokens_after,
            "tokens_saved": max(0, self.estimated_tokens_before - self.estimated_tokens_after),
            "summary_preview": self.summary_preview,
        }


@dataclass
class SectionBudgetReport:
    section: str
    budget_tokens: int | None
    estimated_tokens_before: int
    estimated_tokens_after: int
    item_count_before: int
    item_count_after: int
    compressed_count: int = 0
    trimmed_count: int = 0
    summarised_count: int = 0

    @property
    def over_budget_before(self) -> bool:
        return self.budget_tokens is not None and self.estimated_tokens_before > self.budget_tokens

    @property
    def over_budget_after(self) -> bool:
        return self.budget_tokens is not None and self.estimated_tokens_after > self.budget_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "section": self.section,
            "budget_tokens": self.budget_tokens,
            "estimated_tokens_before": self.estimated_tokens_before,
            "estimated_tokens_after": self.estimated_tokens_after,
            "tokens_saved": max(0, self.estimated_tokens_before - self.estimated_tokens_after),
            "item_count_before": self.item_count_before,
            "item_count_after": self.item_count_after,
            "compressed_count": self.compressed_count,
            "trimmed_count": self.trimmed_count,
            "summarised_count": self.summarised_count,
            "over_budget_before": self.over_budget_before,
            "over_budget_after": self.over_budget_after,
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
    compressed_items: list[CompressedContextItem] = field(default_factory=list)
    short_term_summary: ShortTermSummaryReport | None = None
    section_reports: list[SectionBudgetReport] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    model_name: str = "generic"
    chars_per_token: float = CHARS_PER_TOKEN_ESTIMATE
    compression_enabled: bool = True
    short_term_summarization_enabled: bool = True
    budget_aware_graph_expansion: bool = True

    @property
    def trimmed_count(self) -> int:
        return len(self.trimmed_items)

    @property
    def compressed_count(self) -> int:
        return len(self.compressed_items)

    @property
    def over_budget_after_trimming(self) -> bool:
        return self.estimated_prompt_tokens_after > self.available_prompt_tokens

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "max_prompt_tokens": self.max_prompt_tokens,
            "reserved_response_tokens": self.reserved_response_tokens,
            "available_prompt_tokens": self.available_prompt_tokens,
            "model_name": self.model_name,
            "chars_per_token": self.chars_per_token,
            "compression_enabled": self.compression_enabled,
            "short_term_summarization_enabled": self.short_term_summarization_enabled,
            "budget_aware_graph_expansion": self.budget_aware_graph_expansion,
            "estimated_prompt_tokens_before": self.estimated_prompt_tokens_before,
            "estimated_prompt_tokens_after": self.estimated_prompt_tokens_after,
            "trimmed_count": self.trimmed_count,
            "trimmed_items": [item.to_dict() for item in self.trimmed_items],
            "compressed_count": self.compressed_count,
            "compressed_items": [item.to_dict() for item in self.compressed_items],
            "short_term_summary": self.short_term_summary.to_dict() if self.short_term_summary else None,
            "section_reports": [item.to_dict() for item in self.section_reports],
            "over_budget_after_trimming": self.over_budget_after_trimming,
            "notes": self.notes,
        }


class ContextBudgeter:
    """Applies a V2 prompt budget to a ContextPackage.

    Safe rules:
    - it never deletes or edits database memories;
    - compression is request-local prompt text only;
    - protected core memories are not dropped unless explicitly allowed;
    - old short-term chat can be summarised before being dropped;
    - the report explains section budgets, compression, trimming, and leftovers.
    """

    def __init__(self, policy: ContextBudgetPolicy | None = None):
        self.policy = policy or ContextBudgetPolicy()

    def apply(self, context_package: Any) -> ContextBudgetReport:
        self._ensure_compression_store(context_package)

        before = self._estimate_prompt_tokens(context_package)
        report = ContextBudgetReport(
            enabled=bool(self.policy.enforce),
            max_prompt_tokens=int(self.policy.max_prompt_tokens),
            reserved_response_tokens=int(self.policy.reserved_response_tokens),
            available_prompt_tokens=int(self.policy.available_prompt_tokens),
            estimated_prompt_tokens_before=before,
            estimated_prompt_tokens_after=before,
            model_name=self.policy.model_name,
            chars_per_token=self.policy.chars_per_token,
            compression_enabled=bool(self.policy.compression_enabled),
            short_term_summarization_enabled=bool(self.policy.short_term_summarization_enabled),
            budget_aware_graph_expansion=bool(self.policy.budget_aware_graph_expansion),
        )

        initial_sections = self._section_snapshots(context_package)

        if not self.policy.enforce:
            report.section_reports = self._build_section_reports(
                before_sections=initial_sections,
                after_sections=self._section_snapshots(context_package),
                compressed_by_section={},
                trimmed_by_section={},
                summarised_by_section={},
            )
            report.notes.append("Context budget enforcement is disabled for this request.")
            return report

        if not self.policy.allow_core_trimming:
            report.notes.append("Core/profile memories are protected from token-budget trimming.")

        compressed_by_section: dict[str, int] = {}
        trimmed_by_section: dict[str, int] = {}
        summarised_by_section: dict[str, int] = {}

        if self.policy.compression_enabled and self._has_explicit_section_budgets():
            compressed_by_section = self._compress_oversized_sections(context_package, report)
        elif self.policy.compression_enabled:
            report.notes.append("Prompt compression is ready, but no explicit section_budget_tokens were provided for this request.")
        else:
            report.notes.append("Prompt compression is disabled for this request.")

        if self.policy.short_term_summarization_enabled:
            summary_report = self._summarise_short_term_if_helpful(context_package)
            if summary_report is not None:
                report.short_term_summary = summary_report
                summarised_by_section["short_term"] = summary_report.original_message_count - summary_report.kept_recent_message_count
        else:
            report.notes.append("Short-term summarisation is disabled for this request.")

        section_trim_counts = self._trim_sections_to_soft_budgets(context_package, report)
        for section, count in section_trim_counts.items():
            trimmed_by_section[section] = trimmed_by_section.get(section, 0) + count

        if self._estimate_prompt_tokens(context_package) > self.policy.available_prompt_tokens:
            total_trim_counts = self._trim_to_total_budget(context_package, report)
            for section, count in total_trim_counts.items():
                trimmed_by_section[section] = trimmed_by_section.get(section, 0) + count

        after = self._estimate_prompt_tokens(context_package)
        report.estimated_prompt_tokens_after = after
        report.section_reports = self._build_section_reports(
            before_sections=initial_sections,
            after_sections=self._section_snapshots(context_package),
            compressed_by_section=compressed_by_section,
            trimmed_by_section=trimmed_by_section,
            summarised_by_section=summarised_by_section,
        )

        if report.compressed_count:
            report.notes.append("Some context items were compressed before any last-resort dropping was attempted.")
        if report.short_term_summary:
            report.notes.append("Older short-term messages were summarised into one compact working-memory note.")
        if report.trimmed_count == 0 and after <= self.policy.available_prompt_tokens:
            report.notes.append("Context fits within the configured token budget.")
        elif report.trimmed_count and after <= self.policy.available_prompt_tokens:
            report.notes.append("Context was trimmed to fit the configured token budget.")
        elif after > self.policy.available_prompt_tokens:
            report.notes.append("Context is still over budget after compression and all allowed trimming steps.")

        return report

    def _ensure_compression_store(self, context_package: Any) -> None:
        if not hasattr(context_package, "compressed_item_text") or getattr(context_package, "compressed_item_text") is None:
            setattr(context_package, "compressed_item_text", {})

    def _estimate_prompt_tokens(self, context_package: Any) -> int:
        return estimate_tokens(
            context_package.to_system_prompt(),
            model_name=self.policy.model_name,
            chars_per_token=self.policy.chars_per_token,
        )

    def _estimate_text_tokens(self, text: str | None) -> int:
        return estimate_tokens(text, model_name=self.policy.model_name, chars_per_token=self.policy.chars_per_token)

    def _effective_content_for_item(self, context_package: Any, source: str, item: Any) -> str:
        compressed_store = getattr(context_package, "compressed_item_text", {}) or {}
        compressed = compressed_store.get(context_item_key(source, item))
        if compressed is not None:
            return compressed
        return self._content_for_trimmed_item(item)

    def _section_snapshots(self, context_package: Any) -> dict[str, dict[str, int]]:
        snapshots: dict[str, dict[str, int]] = {}
        for definition in SECTION_DEFINITIONS:
            items = self._items_for_section(context_package, definition)
            snapshots[definition.name] = {
                "tokens": sum(self._estimate_text_tokens(self._effective_content_for_item(context_package, definition.source, item)) for item in items),
                "items": len(items),
                "budget": self.policy.section_budget_for(definition.name) or 0,
            }
        return snapshots

    def _build_section_reports(
        self,
        before_sections: dict[str, dict[str, int]],
        after_sections: dict[str, dict[str, int]],
        compressed_by_section: dict[str, int],
        trimmed_by_section: dict[str, int],
        summarised_by_section: dict[str, int],
    ) -> list[SectionBudgetReport]:
        reports: list[SectionBudgetReport] = []
        for definition in SECTION_DEFINITIONS:
            before = before_sections.get(definition.name, {})
            after = after_sections.get(definition.name, {})
            budget = self.policy.section_budget_for(definition.name)
            reports.append(
                SectionBudgetReport(
                    section=definition.name,
                    budget_tokens=budget,
                    estimated_tokens_before=int(before.get("tokens", 0)),
                    estimated_tokens_after=int(after.get("tokens", 0)),
                    item_count_before=int(before.get("items", 0)),
                    item_count_after=int(after.get("items", 0)),
                    compressed_count=int(compressed_by_section.get(definition.name, 0)),
                    trimmed_count=int(trimmed_by_section.get(definition.name, 0)),
                    summarised_count=int(summarised_by_section.get(definition.name, 0)),
                )
            )
        return reports

    def _has_explicit_section_budgets(self) -> bool:
        return bool(self.policy.section_budget_tokens)

    def _compress_oversized_sections(self, context_package: Any, report: ContextBudgetReport) -> dict[str, int]:
        compressed_by_section: dict[str, int] = {}
        for definition in SECTION_DEFINITIONS:
            if definition.name == "short_term":
                # Short-term has a better specialised tool: summarise older turns.
                continue
            budget = self.policy.section_budget_for(definition.name)
            if budget is None:
                continue

            items = self._items_for_section(context_package, definition)
            if not items:
                continue

            section_tokens = sum(self._estimate_text_tokens(self._content_for_trimmed_item(item)) for item in items)
            if section_tokens <= budget:
                continue

            target_item_tokens = max(8, int((budget / max(1, len(items))) * DEFAULT_COMPRESSION_RATIO))
            largest_items = sorted(
                items,
                key=lambda item: self._estimate_text_tokens(self._content_for_trimmed_item(item)),
                reverse=True,
            )

            for item in largest_items:
                if section_tokens <= budget:
                    break
                original = self._content_for_trimmed_item(item)
                before_tokens = self._estimate_text_tokens(original)
                if before_tokens <= target_item_tokens + 4:
                    continue
                compressed = compress_text(
                    original,
                    target_tokens=target_item_tokens,
                    model_name=self.policy.model_name,
                    chars_per_token=self.policy.chars_per_token,
                )
                after_tokens = self._estimate_text_tokens(compressed)
                if after_tokens >= before_tokens:
                    continue

                getattr(context_package, "compressed_item_text")[context_item_key(definition.source, item)] = compressed
                section_tokens -= before_tokens - after_tokens
                compressed_by_section[definition.name] = compressed_by_section.get(definition.name, 0) + 1
                report.compressed_items.append(
                    CompressedContextItem(
                        source=definition.source,
                        memory_id=self._id_for_trimmed_item(item),
                        estimated_tokens_before=before_tokens,
                        estimated_tokens_after=after_tokens,
                        reason=f"section_budget_exceeded_compress_{definition.name}",
                        content_preview_before=compact_preview(original),
                        content_preview_after=compact_preview(compressed),
                    )
                )

        return compressed_by_section

    def _summarise_short_term_if_helpful(self, context_package: Any) -> ShortTermSummaryReport | None:
        definition = SECTION_BY_NAME["short_term"]
        messages = self._items_for_section(context_package, definition)
        if len(messages) < 4:
            return None

        budget = self.policy.section_budget_for("short_term")
        before_tokens = sum(self._estimate_text_tokens(self._content_for_trimmed_item(item)) for item in messages)
        prompt_over_budget = self._estimate_prompt_tokens(context_package) > self.policy.available_prompt_tokens
        section_over_budget = budget is not None and before_tokens > budget
        if not prompt_over_budget and not section_over_budget:
            return None

        keep_recent = min(2, len(messages) - 1)
        older_messages = messages[:-keep_recent]
        recent_messages = messages[-keep_recent:]
        summary_text = self._summarise_short_term_messages(older_messages)
        summary_message = ShortTermMessage(role="system", content=summary_text)
        replacement = [summary_message] + list(recent_messages)
        after_tokens = sum(self._estimate_text_tokens(self._content_for_trimmed_item(item)) for item in replacement)

        if after_tokens >= before_tokens:
            return None

        setattr(context_package, definition.attr_name, replacement)
        return ShortTermSummaryReport(
            original_message_count=len(messages),
            kept_recent_message_count=len(recent_messages),
            estimated_tokens_before=before_tokens,
            estimated_tokens_after=after_tokens,
            summary_preview=compact_preview(summary_text, max_chars=240),
        )

    def _summarise_short_term_messages(self, messages: list[Any]) -> str:
        snippets: list[str] = []
        for message in messages:
            role = getattr(message, "role", "message")
            created_at = getattr(message, "created_at", None)
            if hasattr(created_at, "astimezone"):
                created = created_at.astimezone(timezone.utc).strftime("%H:%M")
                prefix = f"{role}@{created}"
            else:
                prefix = str(role)
            content = compact_preview(getattr(message, "content", ""), max_chars=110)
            if content:
                snippets.append(f"{prefix}: {content}")

        joined = " | ".join(snippets)
        return f"Earlier short-term conversation summary: {joined}"

    def _trim_sections_to_soft_budgets(self, context_package: Any, report: ContextBudgetReport) -> dict[str, int]:
        trimmed_by_section: dict[str, int] = {}
        if not self._has_explicit_section_budgets():
            return trimmed_by_section

        for definition in SECTION_DEFINITIONS:
            if definition.name not in self.policy.section_budget_tokens:
                continue
            if definition.name == "core" and not self.policy.allow_core_trimming:
                continue
            budget = self.policy.section_budget_for(definition.name)
            if budget is None:
                continue
            items = self._items_for_section(context_package, definition)
            while items and self._section_tokens(context_package, definition, items) > budget:
                removed = self._pop_trim_item(items, definition)
                self._record_trim(report, removed, definition.source, f"section_budget_exceeded_trim_{definition.name}")
                trimmed_by_section[definition.name] = trimmed_by_section.get(definition.name, 0) + 1
        return trimmed_by_section

    def _trim_to_total_budget(self, context_package: Any, report: ContextBudgetReport) -> dict[str, int]:
        trimmed_by_section: dict[str, int] = {}
        trim_plan = [
            ("raw", "context_budget_exceeded_trim_raw_first"),
            ("episodic", "context_budget_exceeded_trim_weak_episodic"),
            ("knowledge_relations", "context_budget_exceeded_trim_knowledge_relation_before_core_context"),
            ("semantic", "context_budget_exceeded_trim_weak_semantic"),
            ("lorebook", "context_budget_exceeded_trim_lorebook_after_memories"),
            ("entity_states", "context_budget_exceeded_trim_entity_state_after_lorebook"),
            ("procedural_skills", "context_budget_exceeded_trim_procedural_skill_after_entity_state"),
            ("goals", "context_budget_exceeded_trim_goal_after_procedural_skill"),
            ("short_term", "context_budget_exceeded_trim_oldest_short_term"),
        ]
        if self.policy.allow_core_trimming:
            trim_plan.append(("core", "context_budget_exceeded_trim_core_last_resort"))

        for section_name, reason in trim_plan:
            definition = SECTION_BY_NAME[section_name]
            items = self._items_for_section(context_package, definition)
            while items and self._estimate_prompt_tokens(context_package) > self.policy.available_prompt_tokens:
                removed = self._pop_trim_item(items, definition)
                self._record_trim(report, removed, definition.source, reason)
                trimmed_by_section[definition.name] = trimmed_by_section.get(definition.name, 0) + 1
            if self._estimate_prompt_tokens(context_package) <= self.policy.available_prompt_tokens:
                break

        return trimmed_by_section

    def _items_for_section(self, context_package: Any, definition: SectionDefinition) -> list[Any]:
        items = getattr(context_package, definition.attr_name, None)
        if not isinstance(items, list):
            return []
        return items

    def _section_tokens(self, context_package: Any, definition: SectionDefinition, items: list[Any]) -> int:
        return sum(
            self._estimate_text_tokens(self._effective_content_for_item(context_package, definition.source, item))
            for item in items
        )

    def _pop_trim_item(self, items: list[Any], definition: SectionDefinition) -> Any:
        if definition.trim_from_front:
            return items.pop(0)
        return items.pop()

    def _record_trim(self, report: ContextBudgetReport, item: Any, source: str, reason: str) -> None:
        content = self._content_for_trimmed_item(item)
        report.trimmed_items.append(
            TrimmedContextItem(
                source=source,
                memory_id=self._id_for_trimmed_item(item),
                estimated_tokens=self._estimate_text_tokens(content),
                reason=reason,
                content_preview=compact_preview(content),
            )
        )

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

        # ShortTermMessage objects use role/content and are not database records.
        role = getattr(item, "role", None)
        if role is not None and getattr(item, "created_at", None) is not None:
            return f"{role}: {getattr(item, 'content', '')}"

        skill_key = getattr(item, "skill_key", None)
        if skill_key is not None:
            title = getattr(item, "title", "") or skill_key
            skill_type = getattr(item, "skill_type", "")
            status = getattr(item, "status", "")
            priority = getattr(item, "priority", "")
            description = getattr(item, "description", "")
            notes = getattr(item, "notes", "")
            trigger = getattr(item, "trigger", "")
            procedure = getattr(item, "procedure", "")
            return (
                f"{title} | skill_key={skill_key} | type={skill_type} | status={status} | "
                f"priority={priority} | trigger={trigger} | procedure={procedure} | "
                f"description={description} | notes={notes}"
            )

        goal_key = getattr(item, "goal_key", None)
        if goal_key is not None:
            title = getattr(item, "title", "") or goal_key
            status = getattr(item, "status", "")
            priority = getattr(item, "priority", "")
            description = getattr(item, "description", "")
            notes = getattr(item, "notes", "")
            plan_steps = getattr(item, "plan_steps", "")
            return f"{title} | goal_key={goal_key} | status={status} | priority={priority} | description={description} | plan_steps={plan_steps} | notes={notes}"

        relation_type = getattr(item, "relation_type", None)
        source_type = getattr(item, "source_type", None)
        target_type = getattr(item, "target_type", None)
        if relation_type is not None and source_type is not None and target_type is not None:
            source_id = getattr(item, "source_id", "")
            target_id = getattr(item, "target_id", "")
            description = getattr(item, "description", "")
            evidence = getattr(item, "evidence", "")
            return f"{source_type}:{source_id} {relation_type} {target_type}:{target_id} | description={description} | evidence={evidence}"

        entity_name = getattr(item, "entity_name", "") or getattr(item, "entity_id", "")
        state_kind = getattr(item, "state_kind", None)
        if state_kind is not None:
            attributes = getattr(item, "attributes", None)
            if attributes is None:
                attributes = getattr(item, "attributes_json", None)
            notes = getattr(item, "notes", "")
            return f"{entity_name} | kind={state_kind} | attributes={attributes or {}} | notes={notes or ''}"

        title = getattr(item, "title", None)
        if title is not None:
            return str(title)

        return str(item)
