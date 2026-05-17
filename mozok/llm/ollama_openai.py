from __future__ import annotations

from mozok.config import get_settings
from mozok.llm.model_router import resolve_model


class OllamaOpenAIClient:
    """Tiny wrapper around Ollama's OpenAI-compatible API."""

    def __init__(self, default_role: str = "default"):
        try:
            from openai import OpenAI
        except Exception as exc:  # noqa: BLE001 - preserve the real dependency error.
            raise RuntimeError(
                "Could not import the openai package. Install requirements.txt "
                "before using Ollama/OpenAI-compatible LLM calls."
            ) from exc

        settings = get_settings()
        self.default_role = default_role
        self.model = resolve_model(model_role=default_role, settings=settings)
        self.last_model = self.model
        self.client = OpenAI(
            base_url=settings.ollama_openai_base_url,
            api_key="ollama",
        )

    def chat(self, system_prompt: str, user_message: str, temperature: float = 0.7, model: str | None = None, model_role: str | None = None) -> str:
        selected_model = resolve_model(model=model, model_role=model_role or self.default_role)
        self.last_model = selected_model
        self.model = selected_model
        response = self.client.chat.completions.create(
            model=selected_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
        )
        return response.choices[0].message.content or ""
