"""Application configuration loaded from environment variables / .env file."""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # --- App ---
    # The assistant's display name. Change this to rebrand the whole app.
    assistant_name: str = "Shashi's Bot"
    app_name: str = "ChatBot API"
    app_version: str = "2.1.0"
    debug: bool = False

    # --- Groq / LLM ---
    groq_api_key: str | None = None
    default_model: str = "llama-3.3-70b-versatile"
    default_temperature: float = 0.7
    default_max_tokens: int = 4096
    request_timeout: float = 120.0
    # System prompt applied when the client does not supply one.
    system_prompt: str = (
        "You are {name}, a helpful, knowledgeable and friendly AI assistant. "
        "Answer clearly and concisely. Use Markdown for formatting and fenced "
        "code blocks with a language tag for any code. When the user has "
        "attached documents, ground your answers in their content and cite the "
        "file name when you refer to it."
    )

    # How many of the most recent messages to send back as context.
    max_history_messages: int = 30

    # --- File uploads / document context ---
    max_upload_mb: int = 100         # reject files larger than this
    max_doc_chars: int = 16000       # truncate each extracted document to this
    max_context_chars: int = 48000   # cap on combined attachment text per request

    # --- Persistence ---
    database_url: str = "sqlite:////app/data/chat.db"

    # --- CORS (comma separated list, or "*" for all) ---
    cors_origins: str = "*"

    @property
    def cors_origin_list(self) -> List[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def llm_enabled(self) -> bool:
        return bool(self.groq_api_key and self.groq_api_key.strip())

    @property
    def effective_system_prompt(self) -> str:
        """System prompt with the assistant name substituted in."""
        try:
            return self.system_prompt.format(name=self.assistant_name)
        except (KeyError, IndexError):
            return self.system_prompt


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
