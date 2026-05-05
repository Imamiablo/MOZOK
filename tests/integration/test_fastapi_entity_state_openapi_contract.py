from fastapi.testclient import TestClient

from mozok.api.main import app


def test_entity_state_routes_exist_in_openapi():
    client = TestClient(app)
    response = client.get("/openapi.json")
    assert response.status_code == 200

    paths = response.json()["paths"]

    assert "/entity-states/upsert" in paths
    assert "/entity-states/{state_id}" in paths
    assert "/agents/{agent_id}/entity-states" in paths
    assert "/agents/{agent_id}/entity-states/context" in paths

    assert "post" in paths["/entity-states/upsert"]
    assert "patch" in paths["/entity-states/{state_id}"]
    assert "delete" in paths["/entity-states/{state_id}"]
    assert "get" in paths["/agents/{agent_id}/entity-states"]
    assert "get" in paths["/agents/{agent_id}/entity-states/context"]
