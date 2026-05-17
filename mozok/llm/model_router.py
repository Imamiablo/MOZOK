from __future__ import annotations

import json
from typing import Any

from mozok.config import Settings, get_settings


ROLE_FIELDS = {
    "default": "llm_default_model",
    "chat": "llm_chat_model",
    "scene": "llm_scene_model",
    "semantic": "llm_semantic_model",
    "fast": "llm_fast_model",
    "reasoning": "llm_reasoning_model",
    "summarizer": "llm_summarizer_model",
    "maintenance": "llm_maintenance_model",
}


def resolve_model(model: str | None = None, model_role: str | None = None, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    aliases = model_aliases(settings)
    explicit = (model or "").strip()
    if explicit:
        return aliases.get(explicit, explicit)
    role = (model_role or "default").strip().lower()
    field = ROLE_FIELDS.get(role, "")
    if field:
        configured = str(getattr(settings, field, "") or "").strip()
        if configured:
            return aliases.get(configured, configured)
    default_model = str(settings.llm_default_model or settings.ollama_model).strip()
    return aliases.get(default_model, default_model)


def model_aliases(settings: Settings | None = None) -> dict[str, str]:
    settings = settings or get_settings()
    raw = str(settings.llm_model_aliases or "").strip()
    if not raw:
        return {}
    try:
        parsed: Any = json.loads(raw)
    except json.JSONDecodeError:
        parsed = _parse_inline_aliases(raw)
    if not isinstance(parsed, dict):
        return {}
    return {str(key).strip(): str(value).strip() for key, value in parsed.items() if str(key).strip() and str(value).strip()}


def _parse_inline_aliases(raw: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for chunk in raw.split(","):
        if "=" not in chunk:
            continue
        key, value = chunk.split("=", 1)
        result[key.strip()] = value.strip()
    return result
