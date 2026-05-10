from mozok.api.main import app


def test_maintenance_v2_routes_are_registered_in_openapi():
    schema = app.openapi()

    assert "/agents/{agent_id}/memory-maintenance/suggestions" in schema["paths"]
    assert "/agents/{agent_id}/memory-maintenance/apply" in schema["paths"]
    assert "/agents/{agent_id}/memory-maintenance/reject" in schema["paths"]


def test_maintenance_v2_request_schemas_are_registered_in_openapi():
    schema = app.openapi()
    components = schema["components"]["schemas"]

    assert "MemoryMaintenanceSuggestionsRequest" in components
    assert "MemoryMaintenanceSuggestionsResponse" in components
    assert "MemoryMaintenanceApplyRejectRequest" in components
    assert "MemoryMaintenanceApplyRejectResponse" in components


def test_maintenance_suggestions_schema_exposes_llm_and_clustering_options():
    schema = app.openapi()
    properties = schema["components"]["schemas"]["MemoryMaintenanceSuggestionsRequest"]["properties"]

    assert "include_llm_reasons" in properties
    assert "include_embedding_clusters" in properties
    assert "similarity_threshold" in properties
    assert "min_cluster_size" in properties
    assert "max_clusters" in properties
