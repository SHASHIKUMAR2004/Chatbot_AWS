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
    """Return a list of {title, img_src, url} image results."""
    limit = limit or settings.search_image_results
    data = _get({"q": query, "categories": "images"})
    images = []
    for r in data.get("results", []):
        src = r.get("img_src") or r.get("thumbnail_src") or r.get("thumbnail")
        if not src:
            continue
        # SearXNG sometimes returns protocol-relative or proxied paths.
        if src.startswith("//"):
            src = "https:" + src
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