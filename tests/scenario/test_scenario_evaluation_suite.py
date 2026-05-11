from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from mozok.core import bot_core
from mozok.db.models import Base, MemoryRecord
from mozok.embeddings.base import EmbeddingService
from mozok.memory.service import MemoryService
from mozok.scenario_evaluation import (
    ScenarioContextExpectations,
    ScenarioEvaluationCase,
    evaluate_context_scenario,
    run_context_scenarios,
)
from mozok.scenario_import.service import BrainPackImportService

# Register all plugin/module tables on Base.metadata before create_all().
from mozok.lorebook.models import AgentLorebookKnowledgeRecord, LorebookEntryRecord  # noqa: F401
from mozok.entity_state.models import AgentEntityStateRecord  # noqa: F401
from mozok.goals.models import AgentGoalRecord  # noqa: F401
from mozok.knowledge_relations.models import KnowledgeRelationRecord  # noqa: F401
from mozok.procedural_skills.models import AgentProceduralSkillRecord  # noqa: F401


class KeywordEmbeddingService(EmbeddingService):
    """Tiny deterministic embedding service for scenario tests.

    It avoids loading sentence-transformers while still exercising the real
    MemoryService add/search flow and the vector-index interface.
    """

    vocabulary = [
        "alice",
        "bob",
        "well",
        "tunnel",
        "map",
        "stone",
        "sunset",
        "rumour",
        "mayor",
        "poison",
    ]

    def embed_text(self, text: str) -> np.ndarray:
        lower = (text or "").lower()
        vector = np.array([float(lower.count(token)) for token in self.vocabulary], dtype="float32")
        norm = float(np.linalg.norm(vector))
        if norm > 0.0:
            vector = vector / norm
        return vector


class InMemoryVectorIndex:
    def __init__(self):
        self.vectors: dict[int, np.ndarray] = {}

    def add(self, memory_id: int, vector: np.ndarray) -> None:
        self.vectors[int(memory_id)] = np.asarray(vector, dtype="float32")

    def search(self, vector: np.ndarray, limit: int = 5) -> list[tuple[int, float]]:
        query = np.asarray(vector, dtype="float32")
        scored = [
            (memory_id, float(np.dot(stored, query)))
            for memory_id, stored in self.vectors.items()
        ]
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[: max(0, int(limit))]

    def clear(self) -> None:
        self.vectors.clear()


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def memory_service(db_session):
    return MemoryService(
        db=db_session,
        embedding_service=KeywordEmbeddingService(),
        vector_index=InMemoryVectorIndex(),
    )


@pytest.fixture()
def imported_scenario(db_session, memory_service, monkeypatch):
    monkeypatch.setattr(bot_core, "get_memory_service", lambda db: memory_service)
    pack_path = Path(__file__).parents[1] / "fixtures" / "brain_packs" / "scenario_evaluation_pack.json"
    pack = json.loads(pack_path.read_text(encoding="utf-8"))

    report = BrainPackImportService(db_session).import_pack(
        pack,
        dry_run=False,
        validate_relations=True,
        atomic=True,
    )

    assert report.errors == []
    assert report.memory_import is not None
    assert report.memory_import["created"] == 2
    assert db_session.query(MemoryRecord).count() == 2
    return report


def alice_well_question_case() -> ScenarioEvaluationCase:
    return ScenarioEvaluationCase(
        name="alice_old_well_question",
        agent_id="npc_alice_eval",
        world_id="scenario_eval_world",
        user_message="Bob asks Alice: what do you know about the old well, tunnels, map, and seventh stone?",
        expectations=ScenarioContextExpectations(
            required_text=[
                "Hide the well tunnel secret",
                "Deflect Well Questions",
                "Alice worries Bob may expose the old well secret",
                "A locked tunnel map is hidden behind the seventh stone",
            ],
            forbidden_text=[
                "Mara poisoned the mayor",
            ],
            required_memory_text=[
                "Alice remembers seeing Bob near the old well after sunset",
            ],
            forbidden_memory_text=[
                "Bob remembers only a public rumour",
            ],
            required_lorebook_keys=["old_well_public", "secret_tunnel_map"],
            forbidden_lorebook_keys=["mayor_poison_truth"],
            required_goal_keys=["hide_well_tunnel_secret"],
            required_procedural_skill_keys=["deflect_well_questions"],
            required_entity_ids=["npc_bob_eval"],
            min_counts={
                "memories": 1,
                "goals": 1,
                "procedural_skills": 1,
                "knowledge_relations": 2,
                "lorebook": 2,
                "entity_states": 1,
            },
        ),
    )


def bob_public_knowledge_case() -> ScenarioEvaluationCase:
    return ScenarioEvaluationCase(
        name="bob_public_well_question",
        agent_id="npc_bob_eval",
        world_id="scenario_eval_world",
        user_message="What do you know about the old well after sunset?",
        expectations=ScenarioContextExpectations(
            required_text=[
                "The old well stands beside the ruined chapel",
            ],
            forbidden_text=[
                "A locked tunnel map is hidden behind the seventh stone",
                "Mara poisoned the mayor",
                "Alice worries Bob may expose the old well secret",
            ],
            required_memory_text=[
                "Bob remembers only a public rumour that the old well is unlucky",
            ],
            forbidden_memory_text=[
                "Alice remembers seeing Bob near the old well",
            ],
            required_lorebook_keys=["old_well_public"],
            forbidden_lorebook_keys=["secret_tunnel_map", "mayor_poison_truth"],
            min_counts={"memories": 1, "lorebook": 1},
        ),
    )


def test_scenario_evaluation_imported_brain_pack_context_matches_expectations(
    db_session,
    memory_service,
    imported_scenario,
):
    result = evaluate_context_scenario(
        db=db_session,
        memory_service=memory_service,
        case=alice_well_question_case(),
    )

    assert result.passed, result.errors
    assert result.context is not None
    assert result.debug["used_goals_count"] == 1
    assert result.debug["used_procedural_skills_count"] == 1
    assert result.debug["used_lorebook_entries_count"] == 2


def test_scenario_evaluation_prevents_cross_agent_lore_and_memory_leakage(
    db_session,
    memory_service,
    imported_scenario,
):
    result = evaluate_context_scenario(
        db=db_session,
        memory_service=memory_service,
        case=bob_public_knowledge_case(),
    )

    assert result.passed, result.errors
    assert result.context is not None
    assert result.debug["used_lorebook_entries_count"] == 1
    assert result.debug["used_goals_count"] == 0
    assert result.debug["used_entity_states_count"] == 0


def test_scenario_evaluation_runner_handles_multiple_cases(
    db_session,
    memory_service,
    imported_scenario,
):
    results = run_context_scenarios(
        db=db_session,
        memory_service=memory_service,
        cases=[alice_well_question_case(), bob_public_knowledge_case()],
    )

    assert [result.name for result in results] == [
        "alice_old_well_question",
        "bob_public_well_question",
    ]
    assert all(result.passed for result in results), [result.errors for result in results]


def test_scenario_evaluation_reports_forbidden_context_as_failure(
    db_session,
    memory_service,
    imported_scenario,
):
    case = alice_well_question_case()
    case.expectations.forbidden_text.append("A locked tunnel map is hidden behind the seventh stone")

    result = evaluate_context_scenario(db=db_session, memory_service=memory_service, case=case)

    assert result.passed is False
    assert any("Forbidden prompt text was present" in error for error in result.errors)


def test_scenario_evaluation_debug_output_exposes_pipeline_steps(
    db_session,
    memory_service,
    imported_scenario,
):
    result = evaluate_context_scenario(
        db=db_session,
        memory_service=memory_service,
        case=alice_well_question_case(),
    )

    assert result.passed, result.errors
    steps = [step["step"] for step in result.debug["pipeline_steps"]]
    assert steps == [
        "retrieved",
        "deduped",
        "related_relations_expanded",
        "budget_trimmed",
        "final_prompt",
    ]
    assert result.debug["pipeline_steps"][-1]["used_lorebook_entry_ids"]
