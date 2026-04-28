from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration loaded from environment variables or .env."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    database_url: str = "postgresql+psycopg://mozok:mozok@localhost:5432/mozok"

    llm_provider: str = "ollama_openai"
    ollama_openai_base_url: str = "http://127.0.0.1:11434/v1"
    ollama_model: str = "qwen2.5-coder:32b"

    embedding_provider: str = "sentence_transformers"
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    faiss_index_path: str = "./data/faiss.index"
    faiss_mapping_path: str = "./data/faiss_mapping.json"


@lru_cache
def get_settings() -> Settings:
    return Settings()
