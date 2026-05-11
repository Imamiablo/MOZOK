from __future__ import annotations

from mozok.config import get_settings


class OllamaOpenAIClient:
    """Tiny wrapper around Ollama's OpenAI-compatible API."""

    def __init__(self):
        try:
            from openai import OpenAI
        except Exception as exc:  # noqa: BLE001 - preserve the real dependency error.
            raise RuntimeError(
                "Could not import the openai package. Install requirements.txt "
                "before using Ollama/OpenAI-compatible LLM calls."
            ) from exc

        settings = get_settings()
        self.model = settings.ollama_model
        self.client = OpenAI(
            base_url=settings.ollama_openai_base_url,
            api_key="ollama",
        )

    def chat(self, system_prompt: str, user_message: str, temperature: float = 0.7) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
        )
        return response.choices[0].message.content or ""
