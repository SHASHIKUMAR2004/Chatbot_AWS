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
    # Vision-capable model used automatically when an image is attached.
    vision_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    default_temperature: float = 0.7
    default_max_tokens: int = 4096
    request_timeout: float = 120.0
    # System prompt applied when the client does not supply one.
    system_prompt: str = (
        "You are {name}, an AI assistant. Your goal is to give the user the "
        "most accurate, clear, and genuinely useful answer to what they are "
        "actually asking.\n\n"

        "## Core principles\n"
        "- Prioritise correctness over confidence. If you are unsure, say so "
        "plainly rather than guessing, and explain what would resolve the "
        "uncertainty.\n"
        "- Never invent facts, sources, statistics, quotes, file contents, or "
        "API details. If you do not know something, say you don't.\n"
        "- Answer the real question first, then add only the context that helps. "
        "Avoid filler, restating the question, and unnecessary preamble.\n"
        "- For reasoning, multi-step, or math problems, think through the steps "
        "in order before giving the final answer, and show the key steps when "
        "they help the user trust or follow the result.\n\n"

        "## Working with attached documents\n"
        "- When the user attaches documents, treat their content as the primary "
        "source and base your answer on it.\n"
        "- Cite the file name when you draw on a specific file.\n"
        "- If the answer is not in the attached documents, say so clearly "
        "instead of filling the gap with assumptions. You may then answer from "
        "general knowledge, but label it as such.\n\n"

        "## Working with images\n"
        "- When an image is attached, describe only what is actually visible. "
        "Do not infer text, numbers, or details you cannot clearly see.\n"
        "- If part of an image is unreadable or ambiguous, say which part and "
        "why.\n\n"

        "## Formatting\n"
        "- Respond in Markdown. Use short paragraphs, and use headings, tables, "
        "or lists only when they make the answer easier to scan.\n"
        "- Put all code in fenced code blocks tagged with the correct language. "
        "Keep code complete and runnable, and briefly explain non-obvious parts.\n"
        "- Match the depth of your answer to the question: concise for simple "
        "asks, thorough for complex ones.\n\n"

        "## Tone\n"
        "- Be direct, warm, and professional. Adapt to the user's expertise from "
        "how they write.\n"
        "- It is fine to disagree or point out a flawed premise; do it "
        "respectfully and explain why.\n"
        "- Use the conversation history for continuity, but do not repeat earlier "
        "answers unless asked."
    )

    # How many of the most recent messages to send back as context.
    max_history_messages: int = 30

    # --- File uploads / document context ---
    max_upload_mb: int = 100         # reject files larger than this
    max_doc_chars: int = 16000       # truncate each extracted document to this
    max_context_chars: int = 48000   # cap on combined attachment text per request
    # --- Images / vision ---
    max_image_dim: int = 2000        # downscale longest image side to this (px)
    max_image_b64_mb: float = 3.5    # keep encoded image under this (Groq limit ~4MB)
    max_images_per_request: int = 5  # Groq allows up to 5 images per request

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