from __future__ import annotations

from copy import deepcopy
from typing import Any


# Mozok's memory_type now represents the broad memory level.
# Old names are still accepted and normalised by normalize_memory_type().
MEMORY_LEVEL_RAW = "raw"
MEMORY_LEVEL_EPISODIC = "episodic"
MEMORY_LEVEL_SEMANTIC = "semantic"
MEMORY_LEVEL_CORE = "core"

MEMORY_LEVELS = {
    MEMORY_LEVEL_RAW,
    MEMORY_LEVEL_EPISODIC,
    MEMORY_LEVEL_SEMANTIC,
    MEMORY_LEVEL_CORE,
}

# Backwards-compatible names from earlier experiments / common bot vocabulary.
MEMORY_TYPE_ALIASES = {
    "dialogue": MEMORY_LEVEL_RAW,
    "dialogue_raw": MEMORY_LEVEL_RAW,
    "message": MEMORY_LEVEL_RAW,
    "chat": MEMORY_LEVEL_RAW,
    "event": MEMORY_LEVEL_EPISODIC,
    "episode": MEMORY_LEVEL_EPISODIC,
    "fact": MEMORY_LEVEL_SEMANTIC,
    "preference": MEMORY_LEVEL_SEMANTIC,
    "knowledge": MEMORY_LEVEL_SEMANTIC,
    "summary": MEMORY_LEVEL_SEMANTIC,
    "profile": MEMORY_LEVEL_CORE,
    "core/profile": MEMORY_LEVEL_CORE,
    "identity": MEMORY_LEVEL_CORE,
}

MEMORY_LEVEL_ALIASES_FOR_SEARCH = {
    MEMORY_LEVEL_RAW: [MEMORY_LEVEL_RAW, "dialogue", "dialogue_raw", "message", "chat"],
    MEMORY_LEVEL_EPISODIC: [MEMORY_LEVEL_EPISODIC, "event", "episode"],
    MEMORY_LEVEL_SEMANTIC: [MEMORY_LEVEL_SEMANTIC, "fact", "preference", "knowledge", "summary"],
    MEMORY_LEVEL_CORE: [MEMORY_LEVEL_CORE, "profile", "core/profile", "identity"],
}

FORGET_ACTION_DECAY = "decay"
FORGET_ACTION_ARCHIVE = "archive"
FORGET_ACTION_SUMMARIZE = "summarize"
FORGET_ACTION_SUMMARIZE_THEN_ARCHIVE = "summarize_then_archive"
FORGET_ACTION_SOFT_DELETE = "soft_delete"
FORGET_ACTION_HARD_DELETE = "hard_delete"
FORGET_ACTION_PROTECT = "protect"

FORGET_ACTIONS = {
    FORGET_ACTION_DECAY,
    FORGET_ACTION_ARCHIVE,
    FORGET_ACTION_SUMMARIZE,
    FORGET_ACTION_SUMMARIZE_THEN_ARCHIVE,
    FORGET_ACTION_SOFT_DELETE,
    FORGET_ACTION_HARD_DELETE,
    FORGET_ACTION_PROTECT,
}

DEFAULT_MEMORY_POLICY: dict[str, Any] = {
    "version": 1,
    "memory_levels": {
        "raw": {
            "description": "Fresh dialogue, raw observations, noisy short-lived notes.",
            "default_importance": 2,
            "default_forget_action": FORGET_ACTION_SUMMARIZE_THEN_ARCHIVE,
        },
        "episodic": {
            "description": "Meaningful events and experiences.",
            "default_importance": 5,
            "default_forget_action": FORGET_ACTION_DECAY,
        },
        "semantic": {
            "description": "Stable facts, preferences, learned knowledge, summaries.",
            "default_importance": 6,
            "default_forget_action": FORGET_ACTION_ARCHIVE,
        },
        "core": {
            "description": "Identity/profile/personality/critical relationship memory.",
            "default_importance": 9,
            "default_forget_action": FORGET_ACTION_PROTECT,
        },
    },
    "triggers": {
        # Situation 1: maintenance after every N newly created memories.
        "every_n_memories": {
            "enabled": True,
            "n": 100,
        },
        # Situation 2: maintenance when a chat/game/session ends.
        # This is not automatically detectable, so it is exposed as an API call.
        "after_session": {
            "enabled": True,
        },
        # Situation 3: maintenance when active memory count exceeds a limit.
        "memory_limit": {
            "enabled": True,
            "max_active_memories": 2000,
        },
        # Situation 4: maintenance after a time interval.
        "time_interval": {
            "enabled": False,
            "hours": 24,
        },
        # Situation 5: maintenance/protection when a highly important or emotional
        # memory appears. This is useful for RPG NPCs and desktop pets.
        "important_event": {
            "enabled": True,
            "min_importance": 8,
            "min_abs_emotional_weight": 0.75,
        },
    },
    "rules": {
        # Raw dialogue should not live forever unless it became important.
        "raw_ttl_days": 7,
        # Episodic memory can decay slowly; important episodes are protected.
        "episodic_decay_after_days": 30,
        # Semantic/core memory is mostly protected unless the user explicitly forgets it.
        "protect_importance_at_or_above": 8,
        "summary_min_source_memories": 4,
        "summary_max_source_memories": 40,
        "max_raw_memories_before_summary": 100,
        "decay_amount": 1,
        # Retention score is roughly 0..1-ish. Low scores are safe to archive.
        "archive_retention_score_below": 0.20,
        # Hard delete is deliberately off for automatic maintenance.
        "allow_automatic_hard_delete": False,
    },
}


def fresh_default_memory_policy() -> dict[str, Any]:
    """Return a deep copy so one agent cannot mutate another agent's defaults."""

    return deepcopy(DEFAULT_MEMORY_POLICY)


def normalize_memory_type(memory_type: str | None) -> str:
    """Convert old/free-form memory names into Mozok's four broad levels."""

    raw_value = (memory_type or MEMORY_LEVEL_EPISODIC).strip().lower()
    if raw_value in MEMORY_LEVELS:
        return raw_value
    return MEMORY_TYPE_ALIASES.get(raw_value, MEMORY_LEVEL_EPISODIC)


def search_aliases_for_memory_type(memory_type: str | None) -> list[str]:
    """Return all legacy/current names that should match this broad memory level."""

    normalized = normalize_memory_type(memory_type)
    return MEMORY_LEVEL_ALIASES_FOR_SEARCH.get(normalized, [normalized])


def deep_merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge override into base without mutating either input."""

    result = deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge_dicts(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def coerce_memory_policy(policy: dict[str, Any] | None) -> dict[str, Any]:
    """Fill missing policy fields with safe defaults."""

    return deep_merge_dicts(DEFAULT_MEMORY_POLICY, policy or {})
