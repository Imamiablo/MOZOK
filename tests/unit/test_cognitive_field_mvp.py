from __future__ import annotations

from types import SimpleNamespace

from mozok.cognition.schemas import SensoryInput
from mozok.cognition.service import CognitiveFieldService
from mozok.context.context_builder import ContextBuilder, ContextPackage


class FakeQuery:
    def __init__(self, records):
        self.records = records

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, value):
        return self

    def all(self):
        return list(self.records)


class FakeDb:
    def __init__(self, core_records=None):
        self.core_records = core_records or []

    def query(self, model):
        return FakeQuery(self.core_records)


class FakeMemoryService:
    def search(self, *, agent_id, query, limit, memory_type, update_access=True):
        if memory_type == "semantic":
            return [
                SimpleNamespace(
                    id=101,
                    content="The old well has a hidden tunnel map behind the seventh stone.",
                    memory_type="semantic",
                    importance=9,
                    emotional_weight=0.2,
                    score=0.9,
                    metadata={},
                )
            ]
        return []


def make_agent():
    return SimpleNamespace(
        id="npc_alice",
        name="Alice",
        description="Secretive villager.",
        personality="Careful and observant.",
        system_prompt="Use provided context only.",
    )


def test_cognitive_field_scores_sensory_attention_and_memory_resonance():
    context = ContextPackage(
        agent_id="npc_alice",
        session_id="s1",
        system_prompt="Use context only.",
        agent_name="Alice",
        agent_description="Secretive villager.",
        agent_personality="Careful.",
        current_user_message="What was that sound near the old well?",
        semantic_memories=[
            SimpleNamespace(
                id=42,
                content="Alice remembers a sound from the old well tunnels.",
                memory_type="semantic",
                importance=8,
                emotional_weight=0.5,
                score=0.8,
                metadata={},
            )
        ],
    )

    report = CognitiveFieldService().run(
        context_package=context,
        sensory_inputs=[
            SensoryInput(
                channel="hearing",
                content="A metallic echo comes from the old well.",
                intensity=9,
                attention=9,
                tags=["well", "sound"],
            )
        ],
        attention_focus_keywords=["old well", "sound"],
    )

    assert report.enabled is True
    assert report.read_only is True
    assert report.candidate_count >= 2
    assert report.broadcast.selected_thought_id is not None
    assert report.broadcast.working_memory_line
    assert any(candidate.thought_type == "attend_sensory_signal" for candidate in report.candidates)
    assert any(candidate.thought_type == "recall_memory" for candidate in report.candidates)


def test_context_builder_can_inject_cognitive_broadcast_into_debug_and_prompt():
    builder = ContextBuilder(db=FakeDb(), memory_service=FakeMemoryService())

    context = builder.build(
        agent=make_agent(),
        user_message="What do you know about the old well sound?",
        session_id="s1",
        short_term_limit=0,
        core_limit=0,
        semantic_limit=5,
        episodic_limit=0,
        raw_limit=0,
        update_memory_access=False,
        enforce_token_budget=False,
        enable_cognitive_field=True,
        sensory_inputs=[
            SensoryInput(channel="hearing", content="Quiet knocking from the well.", intensity=7, attention=8)
        ],
        attention_focus_keywords=["well", "sound"],
    )

    debug = context.to_debug_dict()
    prompt = context.to_system_prompt()
    steps = context.pipeline_steps()

    assert debug["cognitive_field"] is not None
    assert debug["cognitive_field"]["architecture"] == "resonance_competition_broadcast"
    assert "Cognitive Field / broadcast focus" in prompt
    assert any(step["step"] == "cognitive_broadcast" for step in steps)


def test_cognitive_field_is_opt_in_for_existing_pipeline_shape():
    context = ContextPackage(
        agent_id="npc_alice",
        session_id="s1",
        system_prompt="Use context only.",
        agent_name="Alice",
        agent_description="Secretive villager.",
        agent_personality="Careful.",
        current_user_message="Hello",
    )

    assert context.cognitive_field is None
    assert [step["step"] for step in context.pipeline_steps()] == [
        "retrieved",
        "deduped",
        "related_relations_expanded",
        "budget_trimmed",
        "final_prompt",
    ]


def test_cognitive_field_routes_are_registered_in_openapi():
    from fastapi.testclient import TestClient

    from mozok.api.main import app

    schema = app.openapi()
    paths = schema["paths"]
    assert "/agents/{agent_id}/cognition/field/debug" in paths

    # Swagger UI reads the served /openapi.json, not the in-memory Python object.
    # Keep this check so the dedicated endpoint remains visible in the live UI.
    served_schema = TestClient(app).get("/openapi.json").json()
    assert "/agents/{agent_id}/cognition/field/debug" in served_schema["paths"]

    debug_schema = schema["components"]["schemas"]["ContextDebugRequest"]
    assert "enable_cognitive_field" in debug_schema["properties"]
    assert "sensory_inputs" in debug_schema["properties"]


def test_cognitive_field_runtime_note_is_neutral():
    from mozok.cognition.schemas import CognitiveFieldReport

    note = CognitiveFieldReport().note.lower()
    assert "attention" in note
    assert "biological" not in note
    assert "phenomenal" not in note
    assert "consciousness" not in note
