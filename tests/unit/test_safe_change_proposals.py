from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mozok.db.session import Base
from mozok.db.models import AgentRecord
from mozok.change_proposals.schemas import ChangeOperation, ChangeProposalAutoPolicyRequest, ChangeProposalCreate, ChangeProposalDecisionRequest
from mozok.change_proposals.service import ChangeProposalService


def make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_change_proposal_create_list_reject():
    db = make_db()
    service = ChangeProposalService(db)

    proposal = service.create(
        "agent_safe",
        ChangeProposalCreate(
            proposal_type="reflection",
            summary="Store a reflection note",
            operations=[ChangeOperation(operation_type="no_op", summary="No-op check")],
        ),
    )

    listed = service.list("agent_safe", status="pending")
    assert listed.proposals[0].proposal_id == proposal.proposal_id

    rejected = service.reject("agent_safe", ChangeProposalDecisionRequest(proposal_ids=[proposal.proposal_id]))
    assert rejected.changed is True
    assert rejected.results[0].status == "rejected"
    assert service.list("agent_safe", status="pending").proposals == []


def test_change_proposal_apply_metadata_patch_with_rollback_snapshot():
    db = make_db()
    service = ChangeProposalService(db)
    proposal = service.create(
        "agent_meta",
        ChangeProposalCreate(
            summary="Update safe metadata",
            operations=[
                ChangeOperation(
                    operation_type="update_agent_metadata",
                    payload={"metadata_patch": {"self_model": {"uncertainty": "medium"}}},
                    summary="Set a self-model uncertainty note",
                )
            ],
        ),
    )

    response = service.apply("agent_meta", ChangeProposalDecisionRequest(proposal_ids=[proposal.proposal_id]))
    agent = db.get(AgentRecord, "agent_meta")

    assert response.changed is True
    assert response.results[0].status == "applied"
    assert response.results[0].rollback_snapshot["agent_id"] == "agent_meta"
    assert agent.metadata_json["self_model"]["uncertainty"] == "medium"


def test_auto_apply_low_risk_skips_medium_risk():
    db = make_db()
    service = ChangeProposalService(db)
    service.create(
        "agent_policy",
        ChangeProposalCreate(
            summary="Safe low-risk no-op",
            risk_level="low",
            operations=[ChangeOperation(operation_type="no_op")],
        ),
    )
    service.create(
        "agent_policy",
        ChangeProposalCreate(
            summary="Medium-risk no-op",
            risk_level="medium",
            operations=[ChangeOperation(operation_type="no_op")],
        ),
    )

    response = service.auto_apply("agent_policy", ChangeProposalAutoPolicyRequest(approval_mode="apply_low_risk"))

    assert response.applied_count == 1
    pending = service.list("agent_policy", status="pending").proposals
    assert len(pending) == 1
    assert pending[0].risk_level == "medium"
