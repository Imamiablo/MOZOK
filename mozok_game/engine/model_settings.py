from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


MODEL_ROLES = ["chat", "scene", "semantic", "fast", "reasoning", "summarizer", "maintenance"]
MODEL_ROLE_GROUPS = {
    "all": list(MODEL_ROLES),
    "powerful": ["chat", "scene", "reasoning"],
    "helper": ["semantic", "fast", "summarizer", "maintenance"],
}


@dataclass(slots=True)
class GameModelSettings:
    role_models: dict[str, str] = field(default_factory=dict)
    available_models: list[str] = field(default_factory=list)

    def model_for_role(self, role: str) -> str:
        return str(self.role_models.get(role, "")).strip()

    def set_model_for_role(self, role: str, model: str) -> None:
        clean_role = str(role).strip().lower()
        if clean_role not in MODEL_ROLES:
            return
        clean_model = str(model).strip()
        if clean_model:
            self.role_models[clean_role] = clean_model
        else:
            self.role_models.pop(clean_role, None)
        self.available_models = _dedupe([*self.available_models, clean_model])

    def to_dict(self) -> dict[str, Any]:
        return {
            "role_models": {role: model for role, model in self.role_models.items() if role in MODEL_ROLES and model},
            "available_models": list(self.available_models),
        }


def model_settings_path(base_dir: Path) -> Path:
    configured = os.getenv("MOZOK_GAME_MODEL_SETTINGS_PATH")
    if configured:
        return Path(configured)
    return base_dir / "user_model_settings.json"


def load_game_model_settings(base_dir: Path) -> GameModelSettings:
    path = model_settings_path(base_dir)
    if not path.exists():
        return GameModelSettings(available_models=_env_models())
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return GameModelSettings(available_models=_env_models())
    role_models = {
        str(role).strip().lower(): str(model).strip()
        for role, model in dict(raw.get("role_models") or {}).items()
        if str(role).strip().lower() in MODEL_ROLES and str(model).strip()
    }
    available = _dedupe([*list(raw.get("available_models") or []), *role_models.values(), *_env_models()])
    return GameModelSettings(role_models=role_models, available_models=available)


def save_game_model_settings(base_dir: Path, settings: GameModelSettings) -> Path:
    path = model_settings_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def discover_ollama_models(base_url: str | None = None, timeout: float = 1.5) -> list[str]:
    """Best-effort local Ollama discovery for the in-game settings panel."""

    try:
        import requests

        raw_url = base_url or os.getenv("OLLAMA_BASE_URL") or os.getenv("OLLAMA_OPENAI_BASE_URL") or "http://127.0.0.1:11434/v1"
        clean = raw_url.rstrip("/")
        if clean.endswith("/v1"):
            clean = clean[:-3]
        response = requests.get(f"{clean}/api/tags", timeout=timeout)
        if response.status_code >= 400:
            return []
        data = response.json()
        models = []
        for item in data.get("models") or []:
            if isinstance(item, dict) and item.get("name"):
                models.append(str(item["name"]))
        return _dedupe(models)
    except Exception:
        return []


def merge_discovered_models(settings: GameModelSettings, models: list[str]) -> None:
    settings.available_models = _dedupe([*settings.available_models, *models, *settings.role_models.values()])


def apply_model_preset(draft: dict[str, str], model: str, group: str) -> dict[str, str]:
    clean = str(model or "").strip()
    roles = MODEL_ROLE_GROUPS.get(str(group or "").strip().lower(), [])
    result = {role: str(value).strip() for role, value in dict(draft or {}).items() if role in MODEL_ROLES and str(value).strip()}
    for role in roles:
        if clean:
            result[role] = clean
        else:
            result.pop(role, None)
    return result


def _env_models() -> list[str]:
    keys = [
        "LLM_DEFAULT_MODEL",
        "LLM_CHAT_MODEL",
        "LLM_SCENE_MODEL",
        "LLM_SEMANTIC_MODEL",
        "LLM_FAST_MODEL",
        "LLM_REASONING_MODEL",
        "LLM_SUMMARIZER_MODEL",
        "LLM_MAINTENANCE_MODEL",
        "OLLAMA_MODEL",
    ]
    return _dedupe(os.getenv(key, "") for key in keys)


def _dedupe(values) -> list[str]:
    result: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if clean and clean not in result:
            result.append(clean)
    return result
