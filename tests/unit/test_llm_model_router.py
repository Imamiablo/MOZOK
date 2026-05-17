from mozok.config import Settings
from mozok.llm.model_router import model_aliases, resolve_model


def test_model_router_resolves_role_and_aliases():
    settings = Settings(
        ollama_model="base-model",
        llm_scene_model="scene-alias",
        llm_model_aliases='{"scene-alias":"qwen-scene:latest"}',
    )

    assert resolve_model(model_role="scene", settings=settings) == "qwen-scene:latest"
    assert resolve_model(model_role="chat", settings=settings) == "base-model"


def test_model_router_explicit_model_wins():
    settings = Settings(ollama_model="base-model", llm_fast_model="fast-model")

    assert resolve_model(model="manual-model", model_role="fast", settings=settings) == "manual-model"


def test_model_aliases_accept_inline_mapping():
    settings = Settings(ollama_model="base-model", llm_model_aliases="fast=qwen-fast,scene=qwen-scene")

    assert model_aliases(settings)["fast"] == "qwen-fast"
