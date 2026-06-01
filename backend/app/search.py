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


def build_search_query(user_message: str, history: List[Dict[str, str]]) -> str:
    """Rewrite a chat message into a focused web-search query using context.

    The raw chat message is often a poor query ("venue is wrong I guess").
    We ask the LLM to turn the message + recent context into a clean search
    query. Falls back to the raw message if rewriting fails or LLM is off.
    """
    from . import llm  # local import to avoid a circular import at module load

    if not llm.llm_available():
        return user_message

    # Build a compact context string from the last few turns.
    recent = history[-6:]
    convo = "\n".join(
        f"{m['role']}: {m['content'][:300]}"
        for m in recent
        if isinstance(m.get("content"), str)
    )
    prompt = [
        {
            "role": "system",
            "content": (
                "You rewrite a user's latest message into a single, concise web "
                "search query (max 12 words). Use the conversation context to "
                "resolve references like 'yesterday', 'that match', or 'the venue'. "
                "Output ONLY the query text, no quotes, no explanation."
            ),
        },
        {
            "role": "user",
            "content": f"Conversation:\n{convo}\n\nLatest message: {user_message}\n\nSearch query:",
        },
    ]
    try:
        q = llm.complete(prompt, max_tokens=40).strip()
        q = q.strip('"').splitlines()[0].strip()
        # Sanity: if the model returned something empty or huge, fall back.
        if not q or len(q) > 200:
            return user_message
        return q
    except Exception as exc:  # noqa: BLE001
        logger.warning("Query rewrite failed: %s", exc)
        return user_message