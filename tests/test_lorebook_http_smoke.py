"""
HTTP smoke tests for Mozok Lorebook endpoints.

These tests talk to a REAL running Mozok API server.

How to run:
1. Start Mozok normally:
   cmd.exe /c start_mozok.bat

2. In another PowerShell window:
   .\.venv\Scripts\python.exe -m pytest tests/test_lorebook_http_smoke.py -q

Optional:
If Mozok runs on another port:
   $env:MOZOK_TEST_BASE_URL="http://127.0.0.1:8000"
   .\.venv\Scripts\python.exe -m pytest tests/test_lorebook_http_smoke.py -q
"""

from __future__ import annotations

import json
import os
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pytest


BASE_URL = os.getenv("MOZOK_TEST_BASE_URL", "http://127.0.0.1:8001")


def _request_json(method: str, path: str, body: dict | None = None) -> dict:
    """
    Send a JSON request to the running Mozok API and return decoded JSON.

    This uses only Python's standard library, so we don't need requests/httpx.
    """
    url = BASE_URL.rstrip("/") + path

    data = None
    headers = {"Accept": "application/json"}

    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = Request(url, data=data, headers=headers, method=method)

    try:
        with urlopen(request, timeout=5) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except URLError as exc:
        pytest.skip(
            f"Mozok API is not reachable at {BASE_URL}. "
            f"Start it first with: cmd.exe /c start_mozok.bat. "
            f"Original error: {exc}"
        )
    except HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        pytest.fail(
            f"HTTP {exc.code} from {method} {path}\n"
            f"Response body:\n{response_body}"
        )


def post_json(path: str, body: dict) -> dict:
    return _request_json("POST", path, body)


def get_json(path: str, query: dict | None = None) -> dict:
    if query:
        path = f"{path}?{urlencode(query)}"
    return _request_json("GET", path)


def response_contains(response: dict, text: str) -> bool:
    """
    Search inside the whole JSON response as text.

    This is intentionally simple and robust while the exact response schema
    is still evolving.
    """
    return text in json.dumps(response, ensure_ascii=False)


def test_public_lorebook_entry_is_visible_to_agent_without_knowledge_link() -> None:
    """
    Public lore should be visible to an agent even if we did not explicitly
    create an agent knowledge record.
    """
    unique = uuid.uuid4().hex[:8]
    world_id = f"test_world_{unique}"
    agent_id = f"npc_bob_{unique}"
    entry_key = f"public_fact_{unique}"

    post_json(
        "/lorebook/upsert",
        {
            "world_id": world_id,
            "entry_key": entry_key,
            "title": "Public Test Fact",
            "content": "Bob should see this public lorebook fact automatically.",
            "category": "test",
            "visibility": "public",
            "importance": 5,
            "tags": ["test", "public", "bob"],
            "metadata": {"test_run": unique},
        },
    )

    context = get_json(
        f"/agents/{agent_id}/lorebook/context",
        {"world_id": world_id},
    )

    assert response_contains(context, entry_key)
    assert response_contains(context, "Bob should see this public lorebook fact automatically.")


def test_restricted_lorebook_entry_is_hidden_until_agent_knows_it() -> None:
    """
    Restricted lore should NOT be visible by default.
    After creating an agent knowledge record, it SHOULD become visible.
    """
    unique = uuid.uuid4().hex[:8]
    world_id = f"test_world_{unique}"
    agent_id = f"npc_bob_{unique}"
    entry_key = f"secret_fact_{unique}"

    post_json(
        "/lorebook/upsert",
        {
            "world_id": world_id,
            "entry_key": entry_key,
            "title": "Restricted Test Secret",
            "content": "Bob knows that the old well hides a tunnel.",
            "category": "secret",
            "visibility": "restricted",
            "importance": 8,
            "tags": ["test", "secret", "bob"],
            "metadata": {"test_run": unique},
        },
    )

    context_before = get_json(
        f"/agents/{agent_id}/lorebook/context",
        {"world_id": world_id},
    )

    assert not response_contains(context_before, entry_key)
    assert not response_contains(context_before, "old well hides a tunnel")

    post_json(
        f"/agents/{agent_id}/lorebook/knowledge",
        {
            "agent_id": agent_id,
            "world_id": world_id,
            "entry_key": entry_key,
            "knowledge_state": "known",
            "confidence": 10,
            "notes": "Bob personally knows this secret.",
            "metadata": {"test_run": unique},
        },
    )

    context_after = get_json(
        f"/agents/{agent_id}/lorebook/context",
        {"world_id": world_id},
    )

    assert response_contains(context_after, entry_key)
    assert response_contains(context_after, "Bob knows that the old well hides a tunnel.")


def test_restricted_lorebook_entry_known_by_one_agent_is_not_visible_to_another_agent() -> None:
    """
    If Bob knows a restricted fact, Alice should not automatically know it.
    This checks that per-agent lorebook knowledge isolation works.
    """
    unique = uuid.uuid4().hex[:8]
    world_id = f"test_world_{unique}"
    bob_id = f"npc_bob_{unique}"
    alice_id = f"npc_alice_{unique}"
    entry_key = f"bob_only_secret_{unique}"

    post_json(
        "/lorebook/upsert",
        {
            "world_id": world_id,
            "entry_key": entry_key,
            "title": "Bob Only Secret",
            "content": "Only Bob knows the hidden tunnel password.",
            "category": "secret",
            "visibility": "restricted",
            "importance": 9,
            "tags": ["test", "secret"],
            "metadata": {"test_run": unique},
        },
    )

    post_json(
        f"/agents/{bob_id}/lorebook/knowledge",
        {
            "agent_id": bob_id,
            "world_id": world_id,
            "entry_key": entry_key,
            "knowledge_state": "known",
            "confidence": 10,
            "notes": "Bob knows this, Alice does not.",
            "metadata": {"test_run": unique},
        },
    )

    bob_context = get_json(
        f"/agents/{bob_id}/lorebook/context",
        {"world_id": world_id},
    )

    alice_context = get_json(
        f"/agents/{alice_id}/lorebook/context",
        {"world_id": world_id},
    )

    assert response_contains(bob_context, entry_key)
    assert response_contains(bob_context, "hidden tunnel password")

    assert not response_contains(alice_context, entry_key)
    assert not response_contains(alice_context, "hidden tunnel password")