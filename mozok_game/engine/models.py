from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Emotion = Literal[
    "neutral",
    "happy",
    "afraid",
    "angry",
    "curious",
    "tired",
    "sad",
    "suspicious",
]

TileKind = Literal["sand", "grass", "forest", "water", "rock", "camp", "cave", "ruins"]


@dataclass(slots=True)
class Position:
    x: int
    y: int

    def copy(self) -> "Position":
        return Position(self.x, self.y)

    def manhattan(self, other: "Position") -> int:
        return abs(self.x - other.x) + abs(self.y - other.y)


@dataclass(slots=True)
class Needs:
    hunger: float = 20.0
    thirst: float = 20.0
    fatigue: float = 10.0
    stress: float = 10.0
    social: float = 30.0
    curiosity: float = 35.0

    def clamp(self) -> None:
        for name in ("hunger", "thirst", "fatigue", "stress", "social", "curiosity"):
            setattr(self, name, max(0.0, min(100.0, float(getattr(self, name)))))

    def tick(self) -> None:
        self.hunger += 2.0
        self.thirst += 3.0
        self.fatigue += 1.5
        self.social += 0.5
        self.curiosity += 0.4
        self.stress = max(0.0, self.stress - 0.4)
        self.clamp()

    @property
    def most_urgent(self) -> tuple[str, float]:
        pairs = {
            "hunger": self.hunger,
            "thirst": self.thirst,
            "fatigue": self.fatigue,
            "stress": self.stress,
            "social": self.social,
            "curiosity": self.curiosity,
        }
        key = max(pairs, key=pairs.get)
        return key, pairs[key]


@dataclass(slots=True)
class SocialState:
    trust: float = 50.0
    fear: float = 5.0
    affinity: float = 30.0
    resentment: float = 5.0

    def clamp(self) -> None:
        for name in ("trust", "fear", "affinity", "resentment"):
            setattr(self, name, max(0.0, min(100.0, float(getattr(self, name)))))


@dataclass(slots=True)
class Agent:
    id: str
    name: str
    role: str
    position: Position
    avatar_folder: str
    personality: str
    needs: Needs = field(default_factory=Needs)
    social_to_player: SocialState = field(default_factory=SocialState)
    emotion: Emotion = "neutral"
    emotion_intensity: float = 0.2
    current_goal: str = "stay_alive"
    inventory: list[str] = field(default_factory=list)
    last_dialogue: str = ""
    last_action: str = "wait"
    last_rationale: str = ""
    brain_focus: str = "Observe the camp."
    brain_focus_score: float = 0.0
    brain_memory: str = ""
    brain_risk: str = "low"
    brain_broadcast: str = "No cognitive broadcast yet."
    memory_snippets: list[str] = field(default_factory=list)
    alive: bool = True


@dataclass(slots=True)
class BrainFlash:
    turn: int
    agent_id: str
    title: str
    content: str
    kind: str = "memory"
    intensity: float = 0.5


@dataclass(slots=True)
class Player:
    position: Position
    inventory: list[str] = field(default_factory=list)
    hunger: float = 10.0
    thirst: float = 10.0
    fatigue: float = 5.0


@dataclass(slots=True)
class WorldObject:
    id: str
    name: str
    kind: str
    position: Position
    interactions: list[str]
    tags: list[str] = field(default_factory=list)
    state: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class WorldEvent:
    turn: int
    event_type: str
    content: str
    source: str = "game"
    salience: float = 5.0
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class AgentIntent:
    agent_id: str
    action_kind: str
    tool_name: str
    parameters: dict[str, Any] = field(default_factory=dict)
    dialogue: str = ""
    emotion: Emotion = "neutral"
    rationale: str = ""
