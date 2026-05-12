from __future__ import annotations

import re
from typing import Any

from mozok.cognition.schemas import SensoryInput
from mozok.perception.schemas import PerceptionCompileResponse, PerceptionEvent, PerceptionProfile, PerceptionReport

_WORD_RE = re.compile(r"[\w']+", re.UNICODE)
_HEARING_WORDS = {"sound", "echo", "hear", "heard", "noise", "voice", "whisper", "bang", "clatter", "knock", "ring", "metallic"}
_VISION_WORDS = {"see", "saw", "look", "light", "dark", "visible", "stands", "colour", "color", "shadow", "movement", "image"}
_BODY_WORDS = {"pain", "heartbeat", "breath", "cold", "hot", "tired", "hungry", "body", "touch", "pressure"}
_TOOL_WORDS = {"file", "email", "calendar", "api", "tool", "result", "search", "upload", "download"}


def _norm(value: Any) -> str:
    return " ".join(str(value or "").lower().replace("_", " ").replace("-", " ").split())


def _tokens(value: Any) -> set[str]:
    return {token for token in _WORD_RE.findall(_norm(value)) if len(token) > 2}


def _keyword_overlap(keywords: list[str], *texts: Any) -> float:
    if not keywords:
        return 0.0
    haystack = _norm(" ".join(str(text) for text in texts if text is not None))
    hits = 0
    for keyword in keywords:
        clean = _norm(keyword)
        if clean and clean in haystack:
            hits += 1
    return hits / max(1, len(keywords))


class PerceptionCompiler:
    """Compile adapter-neutral events into Cognitive Field SensoryInput items.

    This is intentionally deterministic and read-only. External adapters remain
    responsible for deciding what events exist; this service only normalises and
    gates them into attention-ready sensory signals.
    """

    def compile(
        self,
        *,
        events: list[PerceptionEvent] | None = None,
        existing_sensory_inputs: list[SensoryInput] | None = None,
        profile: PerceptionProfile | None = None,
        message: str = "",
    ) -> PerceptionCompileResponse:
        safe_events = [event if isinstance(event, PerceptionEvent) else PerceptionEvent(**event) for event in (events or [])]
        safe_existing = [item if isinstance(item, SensoryInput) else SensoryInput(**item) for item in (existing_sensory_inputs or [])]
        safe_profile = profile if isinstance(profile, PerceptionProfile) else PerceptionProfile(**(profile or {}))

        generated: list[SensoryInput] = []
        skipped: list[dict[str, Any]] = []

        for index, event in enumerate(safe_events):
            channel = self._infer_channel(event)
            if channel not in safe_profile.enabled_channels and not safe_profile.allow_unknown_channels:
                skipped.append({"index": index, "reason": "channel_disabled", "channel": channel, "content": event.content})
                continue

            intensity = self._intensity(event, channel, safe_profile)
            attention = self._attention(event, channel, safe_profile, message)
            if attention < safe_profile.min_attention:
                skipped.append({"index": index, "reason": "below_min_attention", "channel": channel, "attention": round(attention, 3), "content": event.content})
                continue

            generated.append(
                SensoryInput(
                    channel=channel,
                    content=self._summarise_event(event, channel),
                    intensity=round(max(0.0, min(10.0, intensity)), 3),
                    attention=round(max(0.0, min(10.0, attention)), 3),
                    confidence=round(max(0.0, min(1.0, float(event.reliability))), 3),
                    source=event.source,
                    tags=list(dict.fromkeys([*event.tags, event.event_type])),
                    metadata={
                        **event.metadata,
                        "perception_event_type": event.event_type,
                        "compiled_by": "deterministic_perception_compiler",
                    },
                )
            )

        combined = [*safe_existing, *generated]
        combined.sort(key=lambda item: (float(item.attention), float(item.intensity), float(item.confidence)), reverse=True)
        combined = combined[: safe_profile.max_inputs]

        channels = sorted({item.channel for item in combined})
        report = PerceptionReport(
            event_count=len(safe_events),
            existing_sensory_input_count=len(safe_existing),
            generated_sensory_input_count=len(generated),
            output_sensory_input_count=len(combined),
            channels=channels,
            skipped_events=skipped,
            notes=[
                "Read-only perception compilation; no memories, goals, skills, relations, or FAISS entries are modified.",
                "External adapters decide what events exist; this layer normalises them into sensory inputs for Cognitive Field attention competition.",
            ],
        )
        return PerceptionCompileResponse(sensory_inputs=combined, report=report)

    def _infer_channel(self, event: PerceptionEvent) -> str:
        if event.channel_hint:
            return _norm(event.channel_hint).replace(" ", "_") or "world_event"
        text_tokens = _tokens(" ".join([event.content, event.event_type, " ".join(event.tags)]))
        if text_tokens & _HEARING_WORDS:
            return "hearing"
        if text_tokens & _VISION_WORDS:
            return "vision"
        if text_tokens & _BODY_WORDS:
            return "body"
        if text_tokens & _TOOL_WORDS:
            return "tool"
        if _norm(event.event_type) in {"ui", "interface"}:
            return "ui"
        if _norm(event.event_type) in {"chat", "message", "text"}:
            return "text"
        return "world_event"

    def _distance_factor(self, event: PerceptionEvent, profile: PerceptionProfile) -> float:
        if not profile.distance_falloff or event.distance is None:
            return 1.0
        # Adapter-neutral: distance is arbitrary units. 0 -> full strength;
        # around 50 -> roughly half; never collapses to zero.
        return max(0.15, 1.0 / (1.0 + float(event.distance) / 50.0))

    def _intensity(self, event: PerceptionEvent, channel: str, profile: PerceptionProfile) -> float:
        channel_weight = float(profile.channel_weights.get(channel, 1.0))
        return float(event.salience) * channel_weight * self._distance_factor(event, profile)

    def _attention(self, event: PerceptionEvent, channel: str, profile: PerceptionProfile, message: str) -> float:
        base = self._intensity(event, channel, profile)
        keyword_boost = _keyword_overlap(profile.attention_keywords, event.content, event.tags) * 3.0
        message_boost = len(_tokens(message) & _tokens(" ".join([event.content, " ".join(event.tags)]))) * 0.35
        reliability_boost = float(event.reliability) * 0.6
        return base + keyword_boost + message_boost + reliability_boost

    def _summarise_event(self, event: PerceptionEvent, channel: str) -> str:
        content = str(event.content or "").replace("\n", " ").strip()
        if not content:
            content = f"{event.event_type} event on {channel}."
        return content if len(content) <= 360 else content[:357] + "..."
