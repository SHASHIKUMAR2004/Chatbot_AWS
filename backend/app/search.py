"""Web and image search via a self-hosted SearXNG instance.

SearXNG is an open-source metasearch engine. We query its JSON API, which
aggregates results from many engines with no API key. Used to (a) feed text
results into the LLM context for grounded answers, and (b) return image URLs
the frontend renders inline.
"""
from __future__ import annotations

import logging
from typing import Dict, List

import httpx

from .config import settings

logger = logging.getLogger("chatbot.search")


class SearchError(Exception):
    """Raised when search is unavailable or fails."""


def _get(params: Dict[str, str]) -> dict:
    url = settings.searxng_url.rstrip("/") + "/search"
    params = {"format": "json", **params}
    try:
        resp = httpx.get(url, params=params, timeout=settings.search_timeout,
                         headers={"User-Agent": "ChatBot/1.0"})
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError as exc:
        raise SearchError(f"Search service unavailable: {exc}") from exc
    except ValueError as exc:
        raise SearchError("Search returned an invalid response.") from exc


def web_search(query: str, limit: int | None = None) -> List[Dict[str, str]]:
    """Return a list of {title, url, content} text results."""
    limit = limit or settings.search_results
    data = _get({"q": query})
    results = []
    for r in data.get("results", [])[: limit * 2]:
        if not r.get("url"):
            continue
        results.append(
            {
                "title": (r.get("title") or "").strip(),
                "url": r.get("url", ""),
                "content": (r.get("content") or "").strip(),
            }
        )
        if len(results) >= limit:
            break
    return results


def image_search(query: str, limit: int | None = None) -> List[Dict[str, str]]:
    """Return a list of {title, img_src, url} image results, filtering junk."""
    limit = limit or settings.search_image_results
    data = _get({"q": query, "categories": "images"})
    images = []
    for r in data.get("results", []):
        src = r.get("img_src") or r.get("thumbnail_src") or r.get("thumbnail")
        if not src:
            continue
        if src.startswith("//"):
            src = "https:" + src
        low = src.lower()
        # Skip non-displayable or junk sources: data URIs, favicons, svgs,
        # and anything not served over http(s).
        if low.startswith("data:") or not low.startswith("http"):
            continue
        if "favicon" in low or low.endswith(".svg"):
            continue
        images.append(
            {
                "title": (r.get("title") or "").strip(),
                "img_src": src,
                "url": r.get("url", ""),
            }
        )
        if len(images) >= limit:
            break
    return images


def format_results_for_llm(query: str, results: List[Dict[str, str]]) -> str:
    """Turn text results into a context block the model can ground answers on."""
    if not results:
        return (
            f"A web search for '{query}' returned no results. Tell the user you "
            "couldn't find current information on this."
        )
    lines = [
        f"Web search results for '{query}'. Use these to answer, and cite "
        "sources by their number like [1], [2]:\n"
    ]
    for i, r in enumerate(results, 1):
        lines.append(f"[{i}] {r['title']}\n{r['url']}\n{r['content']}\n")
    return "\n".join(lines)


def build_search_query(
    user_message: str,
    history: List[Dict[str, str]],
    for_images: bool = False,
) -> str:
    """Rewrite a chat message into a focused web-search query using context.

    The raw chat message is often a poor query ("I want images of it"). We ask
    the LLM to resolve references ("it", "that match", "yesterday") against the
    recent conversation and produce a clean query. Falls back to the raw
    message if rewriting fails or the LLM is off.
    """
    from . import llm  # local import to avoid a circular import at module load

    if not llm.llm_available():
        return user_message

    # Build a compact context string from the last few turns.
    recent = history[-6:]
    convo = "\n".join(
        f"{m['role']}: {m['content'][:400]}"
        for m in recent
        if isinstance(m.get("content"), str)
    )
    kind = "image search" if for_images else "web search"
    instruction = (
        f"You convert a user's latest message into ONE concise {kind} query "
        "(3-10 words). CRITICAL: resolve every vague reference using the "
        "conversation context. Words like 'it', 'this', 'that', 'them', "
        "'yesterday', 'the match', 'the topic' MUST be replaced with the actual "
        "subject from the conversation. Output ONLY the query text — no quotes, "
        "no labels, no explanation, no thinking."
    )
    examples = (
        "Example:\n"
        "Conversation:\nassistant: ...overview of neural network architectures "
        "(CNN, RNN, Transformer)...\n"
        "Latest message: I want images of it\n"
        "Query: neural network architecture diagram\n\n"
        "Example:\n"
        "Conversation:\nuser: yesterday's IPL score\nassistant: RCB beat GT in "
        "the final\n"
        "Latest message: full scorecard of both sides\n"
        "Query: IPL 2026 final RCB vs GT full scorecard\n\n"
    )
    prompt = [
        {"role": "system", "content": instruction + "\n\n" + examples},
        {
            "role": "user",
            "content": f"Conversation:\n{convo}\n\nLatest message: {user_message}\n\nQuery:",
        },
    ]
    try:
        q = llm.complete(prompt, max_tokens=40, temperature=0.0).strip()
        q = _clean_query(q)
        if not q or len(q) > 200:
            return user_message
        return q
    except Exception as exc:  # noqa: BLE001
        logger.warning("Query rewrite failed: %s", exc)
        return user_message


def _clean_query(q: str) -> str:
    """Strip reasoning, quotes, and labels a model might emit around a query."""
    import re

    # Remove <think>...</think> reasoning blocks some models emit.
    q = re.sub(r"<think>.*?</think>", "", q, flags=re.DOTALL | re.IGNORECASE)
    q = q.strip()
    # Take the last non-empty line (models sometimes reason then answer).
    lines = [ln.strip() for ln in q.splitlines() if ln.strip()]
    if lines:
        q = lines[-1]
    # Drop a leading "Query:" label if present.
    q = re.sub(r"^(query|search)\s*:\s*", "", q, flags=re.IGNORECASE)
    return q.strip().strip('"').strip()