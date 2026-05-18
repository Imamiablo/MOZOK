from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(slots=True)
class GamePerformanceSettings:
    max_llm_ticks_per_turn: int = 1
    llm_tick_cooldown_turns: int = 2
    max_group_chat_llm_replies: int = 1
    social_scene_llm_interval: int = 4
    async_llm_enabled: bool = True
    async_workers: int = 1
    async_pending_limit: int = 8
    async_decision_ttl_turns: int = 4
    compact_payloads: bool = True
    decision_voice_policy: str = "important"
    recent_event_limit: int = 4
    chat_context_chars: int = 2600
    scene_context_chars: int = 2400
    known_object_limit: int = 10


def load_performance_settings() -> GamePerformanceSettings:
    return GamePerformanceSettings(
        max_llm_ticks_per_turn=_int_env("MOZOK_GAME_MAX_LLM_TICKS_PER_TURN", 1),
        llm_tick_cooldown_turns=_int_env("MOZOK_GAME_LLM_TICK_COOLDOWN_TURNS", 2),
        max_group_chat_llm_replies=_int_env("MOZOK_GAME_MAX_GROUP_CHAT_LLM_REPLIES", 1),
        social_scene_llm_interval=_int_env("MOZOK_GAME_SOCIAL_SCENE_LLM_INTERVAL", 4),
        async_llm_enabled=_bool_env("MOZOK_GAME_ASYNC_LLM", True),
        async_workers=max(1, _int_env("MOZOK_GAME_ASYNC_WORKERS", 1)),
        async_pending_limit=_int_env("MOZOK_GAME_ASYNC_PENDING_LIMIT", 8),
        async_decision_ttl_turns=_int_env("MOZOK_GAME_ASYNC_DECISION_TTL_TURNS", 4),
        compact_payloads=_bool_env("MOZOK_GAME_COMPACT_PAYLOADS", True),
        decision_voice_policy=os.getenv("MOZOK_GAME_DECISION_VOICE_POLICY", "important").strip().lower() or "important",
        recent_event_limit=_int_env("MOZOK_GAME_RECENT_EVENT_LIMIT", 4),
        chat_context_chars=_int_env("MOZOK_GAME_CHAT_CONTEXT_CHARS", 2600),
        scene_context_chars=_int_env("MOZOK_GAME_SCENE_CONTEXT_CHARS", 2400),
        known_object_limit=_int_env("MOZOK_GAME_KNOWN_OBJECT_LIMIT", 10),
    )


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}
