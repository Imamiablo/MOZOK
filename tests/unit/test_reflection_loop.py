from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mozok.db.session import Base
from mozok.reflection.schemas import ReflectionRequest
from mozok.reflection.service import ReflectionService


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_reflection_preview_is_read_only_and_creates_signals():
    db = make_db()
    response = ReflectionService(db).reflect(
        ReflectionRequest(
            agent_id="reflect_agent",
            user_message="What do you know about the old well?",
            assistant_response="I would rather not speak of that place.",
            create_change_proposals=False,
        )
    )

    assert response.read_only is True
    assert response.proposal_count == 0
    assert any(signal.signal_type == "turn_summary" for signal in response.signals)


def test_reflection_run_creates_safe_change_proposals():
    db = make_db()
    response = ReflectionService(db).reflect(
        ReflectionRequest(
            agent_id="reflect_agent",
            session_id="s1",
            user_message="What do you know about the old well?",
            assistant_response="I would rather not speak of that place.",
            cognitive_field={
                "winning_thought_id": "skill:1",
                "broadcast": {"selected_label": "Use skill: Deflect", "prompt_guidance": "Deflect unsafe question."},
                "candidates": [{"thought_type": "use_skill", "source_id": "1"}],
            },
            outcome="success",
            feedback="The deflection sounded natural.",
            create_change_proposals=True,
            store_proposals=True,
        )
    )

    assert response.read_only is False
    assert response.proposal_count >= 2
    summaries = {proposal.summary for proposal in response.proposals}
    assert "Store compact post-turn reflection memory" in summaries
    assert "Update last reflection metadata" in summaries
    assert any("skill outcome" in proposal.summary for proposal in response.proposals)
