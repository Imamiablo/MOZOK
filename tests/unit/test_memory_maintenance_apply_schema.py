from __future__ import annotations


def test_memory_maintenance_apply_reject_schemas_are_importable():
    from mozok.schemas.memory import (  # noqa: PLC0415
        MemoryMaintenanceApplyRejectRequest,
        MemoryMaintenanceApplyRejectResponse,
        MemoryMaintenanceApplyRejectResult,
        MemoryMaintenanceSuggestionInput,
    )

    suggestion = MemoryMaintenanceSuggestionInput(
        suggestion_id="archive:memory:42",
        action="archive",
        target_memory_ids=[42],
        reason="Low retention score.",
    )
    request = MemoryMaintenanceApplyRejectRequest(
        selection="selected",
        selected_suggestion_ids=["archive:memory:42"],
        suggestions=[suggestion],
    )

    assert request.selection == "selected"
    assert request.suggestions[0].target_memory_ids == [42]

    result = MemoryMaintenanceApplyRejectResult(
        suggestion_id="archive:memory:42",
        action="archive",
        target_memory_ids=[42],
        status="applied",
        changed=True,
        message="Archived.",
    )
    response = MemoryMaintenanceApplyRejectResponse(
        agent_id="npc_alice",
        mode="apply",
        selection="selected",
        requested_suggestions=1,
        selected_suggestions=1,
        applied=1,
        rejected=0,
        skipped=0,
        relation_protected=0,
        rebuilt_index=True,
        results=[result],
    )

    assert response.results[0].status == "applied"
