from openai import OpenAI
from mozok.config import get_settings


class OllamaOpenAIClient:
    """Tiny wrapper around Ollama's OpenAI-compatible API."""

    def __init__(self):
        settings = get_settings()
        self.model = settings.ollama_model
        self.client = OpenAI(
            base_url=settings.ollama_openai_base_url,
            api_key="ollama",
        )

    def chat(self, system_prompt: str, user_message: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=0.7,
        )
        return response.choices[0].message.content or ""
