from __future__ import annotations

from typing import Any


PRESSURE_AXES = (
    "scarcity",
    "danger",
    "instability",
    "mystery",
    "authority",
    "dependency",
    "secrecy",
    "moral_pressure",
    "exhaustion",
    "opportunity",
)


TAG_PRESSURE_DELTAS: dict[str, dict[str, float]] = {
    "food": {"scarcity": 0.035, "authority": 0.012},
    "supplies": {"scarcity": 0.025, "authority": 0.012},
    "survival": {"scarcity": 0.018, "danger": 0.012},
    "danger": {"danger": 0.045, "mystery": 0.012},
    "toxic": {"danger": 0.035, "moral_pressure": 0.018},
    "cave": {"mystery": 0.045, "danger": 0.02},
    "mystery": {"mystery": 0.04, "opportunity": 0.01},
    "radio": {"mystery": 0.035, "opportunity": 0.015},
    "sound": {"mystery": 0.025, "danger": 0.015},
    "conflict": {"instability": 0.05, "authority": 0.02},
    "social_risk": {"instability": 0.035, "moral_pressure": 0.015},
    "hostile_alarm": {"danger": 0.04, "instability": 0.04},
    "interrupt": {"instability": 0.035, "dependency": 0.012},
    "medical": {"dependency": 0.03, "exhaustion": 0.01},
    "wound": {"dependency": 0.04, "danger": 0.02},
    "weather": {"exhaustion": 0.05, "danger": 0.025},
    "cold": {"exhaustion": 0.045, "dependency": 0.015},
    "rain": {"exhaustion": 0.045, "scarcity": 0.01},
    "decision": {"authority": 0.018, "moral_pressure": 0.015},
    "promise": {"dependency": 0.02, "authority": 0.01},
    "hidden": {"secrecy": 0.04, "mystery": 0.02},
    "secret": {"secrecy": 0.05, "mystery": 0.02},
    "item": {"opportunity": 0.014},
    "tool": {"opportunity": 0.02},
}


EVENT_PRESSURE_DELTAS: dict[str, dict[str, float]] = {
    "item_transfer": {"dependency": 0.012, "opportunity": 0.01},
    "player_take_food": {"scarcity": 0.06, "authority": 0.025, "instability": 0.025},
    "agent_eat": {"scarcity": 0.035},
    "agent_task_interrupted": {"instability": 0.045, "dependency": 0.02},
    "agent_speech_decision": {"authority": 0.015},
    "agent_agent_dialogue": {"instability": -0.008, "dependency": 0.006},
    "agent_initiates_chat": {"dependency": 0.012, "instability": -0.006},
}


def default_pressure_field() -> dict[str, float]:
    return {axis: 0.0 for axis in PRESSURE_AXES}


def apply_event_pressure(pressure: dict[str, float], event: Any) -> None:
    tags = set(getattr(event, "tags", []) or [])
    deltas: dict[str, float] = {}
    for tag in tags:
        _merge_deltas(deltas, TAG_PRESSURE_DELTAS.get(str(tag), {}))
    _merge_deltas(deltas, EVENT_PRESSURE_DELTAS.get(str(getattr(event, "event_type", "")), {}))
    salience = max(0.25, min(1.5, float(getattr(event, "salience", 5.0)) / 7.0))
    for axis, delta in deltas.items():
        pressure[axis] = _clamp01(pressure.get(axis, 0.0) + delta * salience)
    _decay_quiet_axes(pressure, active_axes=set(deltas))


def pressure_summary(pressure: dict[str, float], limit: int = 4) -> str:
    ordered = sorted(pressure.items(), key=lambda item: item[1], reverse=True)
    visible = [f"{axis} {value:.2f}" for axis, value in ordered[:limit] if value > 0.01]
    return ", ".join(visible) if visible else "calm"


def top_pressures(pressure: dict[str, float], limit: int = 3) -> list[str]:
    return [axis for axis, value in sorted(pressure.items(), key=lambda item: item[1], reverse=True)[:limit] if value > 0.01]


def _merge_deltas(target: dict[str, float], source: dict[str, float]) -> None:
    for axis, delta in source.items():
        target[axis] = target.get(axis, 0.0) + delta


def _decay_quiet_axes(pressure: dict[str, float], active_axes: set[str]) -> None:
    for axis in PRESSURE_AXES:
        if axis not in pressure:
            pressure[axis] = 0.0
        if axis not in active_axes:
            pressure[axis] = _clamp01(pressure[axis] * 0.998)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))
