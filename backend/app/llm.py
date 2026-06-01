"""LLM integration layer.

Wraps the Groq client and exposes a uniform streaming interface. If no API
key is configured the module transparently falls back to a *demo mode* that
streams a canned, helpful response — so the whole stack runs end-to-end even
before the user adds their key.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, Iterable, Iterator, List

from .config import settings

logger = logging.getLogger("chatbot.llm")

# Curated fallback catalogue (used when the live Groq /models call is
# unavailable). Kept in sync with GroqCloud production + popular preview models.
_FALLBACK_MODELS: List[Dict[str, str]] = [
    {
        "id": "llama-3.3-70b-versatile",
        "name": "Llama 3.3 70B",
        "description": "Meta's flagship versatile model. Great all-rounder.",
    },
    {
        "id": "llama-3.1-8b-instant",
        "name": "Llama 3.1 8B Instant",
        "description": "Ultra-fast, lightweight responses.",
    },
    {
        "id": "openai/gpt-oss-120b",
        "name": "GPT-OSS 120B",
        "description": "OpenAI open-weight flagship with strong reasoning.",
    },
    {
        "id": "openai/gpt-oss-20b",
        "name": "GPT-OSS 20B",
        "description": "Fast open-weight reasoning model.",
    },
    {
        "id": "meta-llama/llama-4-scout-17b-16e-instruct",
        "name": "Llama 4 Scout 17B",
        "description": "Multimodal-capable, very fast (preview).",
    },
    {
        "id": "qwen/qwen3-32b",
        "name": "Qwen3 32B",
        "description": "Alibaba reasoning model (preview).",
    },
    {
        "id": "groq/compound",
        "name": "Groq Compound (web search)",
        "description": "Agentic system with built-in web search + code exec.",
    },
]

# Compound systems offer built-in web search + code execution. They are always
# offered in the dropdown even if the live /models call omits them.
_COMPOUND_SYSTEMS: List[Dict[str, str]] = [
    {
        "id": "groq/compound",
        "name": "Groq Compound (web search)",
        "description": "Searches the web automatically, with citations.",
    },
    {
        "id": "groq/compound-mini",
        "name": "Groq Compound Mini (web search)",
        "description": "Faster, lighter web-search system.",
    },
]

# Models returned by the live endpoint that are not chat-completion models.
_NON_CHAT_PREFIXES = ("whisper", "playai", "distil-whisper", "orpheus")
_NON_CHAT_SUBSTR = ("guard", "tts", "whisper", "orpheus")

# Substrings identifying vision-capable (multimodal) models on Groq.
_VISION_SUBSTR = ("llama-4", "scout", "maverick", "vision", "llava")


def is_vision_model(model_id: str) -> bool:
    mid = (model_id or "").lower()
    return any(s in mid for s in _VISION_SUBSTR)

_client = None


def _get_client():
    """Lazily build the Groq client. Returns None in demo mode."""
    global _client
    if not settings.llm_enabled:
        return None
    if _client is None:
        from groq import Groq

        _client = Groq(api_key=settings.groq_api_key, timeout=settings.request_timeout)
    return _client


def llm_available() -> bool:
    """True when a real Groq key is configured (not demo mode)."""
    return settings.llm_enabled


def complete(messages: List[Dict[str, str]], model: str | None = None,
             max_tokens: int = 256, temperature: float = 0.2) -> str:
    """Non-streaming single completion. Used for short utility tasks like
    rewriting a search query. Returns "" in demo mode."""
    client = _get_client()
    if client is None:
        return ""
    resp = client.chat.completions.create(
        model=model or settings.default_model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        stream=False,
    )
    return resp.choices[0].message.content or ""


def _pretty_name(model_id: str) -> str:
    tail = model_id.split("/")[-1]
    return tail.replace("-", " ").title()


def list_models() -> List[Dict[str, object]]:
    """Return available chat models. Tries the live Groq catalogue, then falls
    back to the curated list. Always marks the configured default."""
    models: List[Dict[str, object]] = []
    client = _get_client()

    if client is not None:
        try:
            live = client.models.list()
            ids = sorted(
                m.id
                for m in live.data
                if not any(p in m.id.lower() for p in _NON_CHAT_SUBSTR)
                and not m.id.lower().startswith(_NON_CHAT_PREFIXES)
            )
            known = {m["id"]: m for m in _FALLBACK_MODELS}
            for mid in ids:
                meta = known.get(mid, {})
                models.append(
                    {
                        "id": mid,
                        "name": meta.get("name", _pretty_name(mid)),
                        "description": meta.get("description", ""),
                    }
                )
        except Exception as exc:  # pragma: no cover - network dependent
            logger.warning("Live model listing failed (%s); using fallback.", exc)

    if not models:
        models = [dict(m) for m in _FALLBACK_MODELS]

    # Compound "systems" (web search + code exec) are not always returned by
    # the live /models endpoint, so make sure they're offered regardless.
    present = {m["id"] for m in models}
    for compound in _COMPOUND_SYSTEMS:
        if compound["id"] not in present:
            models.append(dict(compound))

    # Ensure default is present and flag it.
    if settings.default_model not in {m["id"] for m in models}:
        models.insert(
            0,
            {
                "id": settings.default_model,
                "name": _pretty_name(settings.default_model),
                "description": "Configured default model.",
            },
        )
    for m in models:
        m["is_default"] = m["id"] == settings.default_model
    return models


def stream_chat(
    messages: List[Dict[str, str]],
    model: str,
    temperature: float,
) -> Iterator[str]:
    """Yield response text chunks for the given chat messages.

    Raises an exception (caught by the caller) on hard API failures so the
    stream can emit a structured error event.
    """
    client = _get_client()
    if client is None:
        yield from _demo_stream(messages)
        return

    completion = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=temperature,
        max_tokens=settings.default_max_tokens,
        stream=True,
    )
    for chunk in completion:
        try:
            delta = chunk.choices[0].delta.content
        except (AttributeError, IndexError):
            delta = None
        if delta:
            yield delta


def _demo_stream(messages: List[Dict[str, object]]) -> Iterator[str]:
    """Stream a friendly placeholder response when no API key is set."""
    # The last user message content may be a string OR a list of parts
    # (text + image_url) when images are attached.
    last_user_raw = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"),
        "",
    )
    has_image = False
    if isinstance(last_user_raw, list):
        texts = [p.get("text", "") for p in last_user_raw if p.get("type") == "text"]
        has_image = any(p.get("type") == "image_url" for p in last_user_raw)
        last_user = " ".join(texts)
    else:
        last_user = last_user_raw

    if has_image:
        text = (
            f"**Demo mode** — I received your image and would analyze it with a "
            f"vision model (`{settings.vision_model}`). Add a `GROQ_API_KEY` to get "
            "a real description and answers about the picture.\n\n"
            f"_You asked:_ {last_user[:200] or '(describe the image)'}"
        )
        for token in _tokenize(text):
            time.sleep(0.01)
            yield token
        return

    # Detect injected document context so demo mode can prove uploads work.
    doc_ctx = next(
        (
            m["content"]
            for m in messages
            if m["role"] == "system"
            and isinstance(m["content"], str)
            and m["content"].startswith("The user has attached")
        ),
        None,
    )
    if doc_ctx:
        files = [
            line.split("BEGIN FILE:", 1)[1].strip().rstrip("-").strip()
            for line in doc_ctx.splitlines()
            if "BEGIN FILE:" in line
        ]
        snippet = " ".join(doc_ctx.split())[:240]
        names = ", ".join(f"`{f}`" for f in files) or "your file"
        text = (
            f"**Demo mode** — I received your upload ({names}) and can read it. "
            "Add a `GROQ_API_KEY` to get real answers grounded in the "
            "document.\n\nHere's a peek at the text I extracted:\n\n"
            f"> {snippet}…\n\n"
            f"_You asked:_ {last_user[:200]}"
        )
        for token in _tokenize(text):
            time.sleep(0.01)
            yield token
        return

    text = (
        f"Hi! I'm **{settings.assistant_name}**, running in **demo mode** "
        "because no `GROQ_API_KEY` is configured yet.\n\n"
        "Everything else works end-to-end: streaming, conversation memory, "
        "history, file uploads, Markdown and code highlighting. To get real "
        "answers from Groq's LLMs:\n\n"
        "1. Create a free key at `https://console.groq.com/keys`\n"
        "2. Add `GROQ_API_KEY=your_key` to the project `.env` file\n"
        "3. Restart the stack with `docker compose up --build`\n\n"
        f"> You said: _{last_user[:280]}_\n\n"
        "Here's a quick code sample to prove formatting works:\n\n"
        "```python\n"
        "def greet(name: str) -> str:\n"
        '    return f"Hello, {name}! Add your Groq key to chat for real."\n'
        "```\n"
    )
    for token in _tokenize(text):
        time.sleep(0.012)
        yield token


def _tokenize(text: str) -> Iterable[str]:
    """Split text into small chunks to simulate token streaming."""
    buf = ""
    for ch in text:
        buf += ch
        if ch in " \n":
            yield buf
            buf = ""
    if buf:
        yield buf