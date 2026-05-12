from mozok.cognition.schemas import SensoryInput
from mozok.perception.schemas import PerceptionEvent, PerceptionProfile
from mozok.perception.service import PerceptionCompiler


def test_perception_compiler_turns_generic_events_into_sensory_inputs():
    response = PerceptionCompiler().compile(
        events=[
            PerceptionEvent(
                content="A metallic sound echoes from the old well.",
                source="game_world",
                salience=8,
                tags=["old well", "metallic"],
            )
        ],
        profile=PerceptionProfile(attention_keywords=["old well"]),
        message="What is that sound near the old well?",
    )

    assert response.report.read_only is True
    assert response.report.event_count == 1
    assert response.report.generated_sensory_input_count == 1
    assert response.sensory_inputs[0].channel == "hearing"
    assert response.sensory_inputs[0].attention > response.sensory_inputs[0].intensity
    assert response.sensory_inputs[0].source == "game_world"


def test_perception_compiler_keeps_existing_direct_sensory_inputs():
    existing = SensoryInput(channel="ui", content="A warning badge is visible.", intensity=4, attention=5)

    response = PerceptionCompiler().compile(
        existing_sensory_inputs=[existing],
        events=[PerceptionEvent(content="Bob is standing near the chapel.", channel_hint="vision", salience=6)],
    )

    channels = {item.channel for item in response.sensory_inputs}
    assert channels == {"ui", "vision"}
    assert response.report.existing_sensory_input_count == 1
    assert response.report.generated_sensory_input_count == 1


def test_perception_profile_can_disable_unknown_channels():
    response = PerceptionCompiler().compile(
        events=[PerceptionEvent(content="A custom adapter pulse.", channel_hint="quantum_antenna", salience=8)],
        profile=PerceptionProfile(enabled_channels=["vision"], allow_unknown_channels=False),
    )

    assert response.sensory_inputs == []
    assert response.report.skipped_events[0]["reason"] == "channel_disabled"
