"""FastAPI smoke/contract tests for the MOZOK API layer.

These tests are intentionally lightweight:
- They do not start PostgreSQL.
- They do not call Ollama.
- They do not touch FAISS.
- They only check that the FastAPI app imports correctly and exposes the
  API contracts that the rest of the project currently relies on.

Why this matters:
Unit tests can prove that individual helper functions work, but they do not
catch mistakes like:
- a broken import in mozok.api.main
- a route accidentally being renamed or removed
- a Pydantic schema change that breaks Swagger/OpenAPI generation
- missing debug/context request fields in the public API contract
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from mozok.api.main import app


client = TestClient(app)


def test_openapi_json_is_available() -> None:
    """The app should import and generate OpenAPI without crashing."""

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")

    spec = response.json()
    assert spec.get("openapi")
    assert spec.get("paths")


def test_core_routes_are_registered() -> None:
    """Important public routes should stay registered in the FastAPI app."""

    spec = client.get("/openapi.json").json()
    paths = spec.get("paths", {})

    assert "/chat" in paths
    assert "post" in paths["/chat"]

    assert "/memories" in paths
    assert "post" in paths["/memories"]

    assert "/debug/context" in paths
    assert "post" in paths["/debug/context"]


def test_debug_context_request_contract_has_budget_fields() -> None:
    """The /debug/context request schema should expose the debug/budget knobs.

    This catches accidental schema regressions where Swagger UI would no longer
    show the controls needed to inspect context construction.
    """

    spec = client.get("/openapi.json").json()
    debug_operation = spec["paths"]["/debug/context"]["post"]

    request_body = debug_operation.get("requestBody")
    assert request_body is not None

    json_schema = request_body["content"]["application/json"]["schema"]
    assert "$ref" in json_schema or "properties" in json_schema

    # OpenAPI may put the actual fields into components/schemas via $ref.
    # Serializing the components gives us a simple, robust contract check.
    schemas_text = json.dumps(spec.get("components", {}).get("schemas", {}))

    expected_fields = [
        "agent_id",
        "session_id",
        "message",
        "short_term_limit",
        "core_limit",
        "semantic_limit",
        "episodic_limit",
        "raw_limit",
        "enforce_token_budget",
        "max_prompt_tokens",
        "reserved_response_tokens",
        "allow_core_trimming",
        "include_full_prompt",
        "prompt_preview_chars",
    ]

    for field_name in expected_fields:
        assert field_name in schemas_text
