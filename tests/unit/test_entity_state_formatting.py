from types import SimpleNamespace

from mozok.entity_state.service import format_entity_state_for_prompt_line
from mozok.schemas.entity_state import EntityStateRead


def test_format_assistant_user_profile_line():
    state = EntityStateRead(
        id=1,
        agent_id="assistant_001",
        entity_id="denys",
        entity_name="Denys",
        entity_type="user",
        role="primary_user",
        state_kind="assistant_user_profile",
        attributes={
            "prefers": ["exact file names", "step-by-step patches"],
            "skill_level": "learning",
        },
        notes="Prefers practical beginner-friendly help.",
    )

    line = format_entity_state_for_prompt_line(state)

    assert line.startswith("- Denys (denys)")
    assert "kind=assistant_user_profile" in line
    assert "type=user" in line
    assert "role=primary_user" in line
    assert "exact file names" in line
    assert "practical beginner-friendly" in line


def test_format_social_relationship_is_not_hard_coded():
    state = SimpleNamespace(
        entity_id="neko_maria",
        entity_name="Neko-Maria",
        entity_type="character",
        role="story_character",
        state_kind="narrative_entity",
        attributes_json={"known_for": "usually blamed for cat misdeeds", "suspicion": "recurring suspect"},
        notes="Useful for narrator continuity, not emotional relationship tracking.",
    )

    line = format_entity_state_for_prompt_line(state)

    assert "narrative_entity" in line
    assert "known_for" in line
    assert "narrator continuity" in line
    assert "trust" not in line
    assert "fear" not in line
