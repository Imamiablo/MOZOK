from mozok.api.main import app


def test_dedup_v2_audit_route_is_registered_in_openapi():
    schema = app.openapi()

    assert "/agents/{agent_id}/memory-dedup/audit" in schema["paths"]


def test_dedup_v2_audit_schemas_are_registered_in_openapi():
    schema = app.openapi()
    components = schema["components"]["schemas"]

    assert "MemoryDedupAuditRequest" in components
    assert "MemoryDedupAuditResponse" in components
    assert "MemoryDedupAuditCandidate" in components
    properties = components["MemoryDedupAuditRequest"]["properties"]
    assert "include_embedding_similarity" in properties
    assert "include_relation_suggestions" in properties
    assert "min_embedding_similarity" in properties
