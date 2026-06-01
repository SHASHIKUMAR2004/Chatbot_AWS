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
    assistant_name: str = "ChatBot"
    app_name: str = "ChatBot API"
    app_version: str = "2.1.0"
    debug: bool = False

    # --- Groq / LLM ---
    groq_api_key: str | None = None
    default_model: str = "openai/gpt-oss-120b"
    # Vision-capable model used automatically when an image is attached.
    vision_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"
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
    # gpt-oss-120b has a 128K context window, so we can keep generous history.
    max_history_messages: int = 30
    # Soft cap on characters of history per request. Large enough to keep
    # conversations coherent; if a model's TPM limit is still exceeded, the
    # backend surfaces a clear "switch model" message instead of silently
    # dropping context. Oldest history is dropped first only past this cap.
    max_prompt_chars: int = 60000

    # --- File uploads / document context ---
    max_upload_mb: int = 100         # reject files larger than this
    max_doc_chars: int = 16000       # truncate each extracted document to this
    max_context_chars: int = 48000   # cap on combined attachment text per request
    # --- Images / vision ---
    max_image_dim: int = 2000        # downscale longest image side to this (px)
    max_image_b64_mb: float = 3.5    # keep encoded image under this (Groq limit ~4MB)
    max_images_per_request: int = 5  # Groq allows up to 5 images per request

    # --- Web search (SearXNG, self-hosted) ---
    searxng_url: str = "http://searxng:8080"   # internal docker network address
    search_enabled: bool = True
    search_results: int = 4          # text results fed to the model (keep small for TPM)
    search_snippet_chars: int = 350  # cap each result's snippet to limit tokens
    search_image_results: int = 6    # image results returned to the UI
    search_timeout: float = 12.0

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