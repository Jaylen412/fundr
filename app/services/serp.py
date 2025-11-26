import time
from contextvars import ContextVar
from typing import Any, Dict

import httpx
from fastapi import HTTPException

from app.core.config import settings, KNOWN_CHAINS
from app.services.db import _DETAILS_CACHE, _REVIEWS_CACHE, _fresh

# =========================
# Budget & Caches
# =========================

SERP_MAX_CALLS_PER_REQUEST = 7      # 1 discovery + (top-3 * [details + reviews])
REVIEWS_SORT = "newest"

_serp_calls = ContextVar("serp_calls", default=0)

def _count_serp():
    n = _serp_calls.get()
    if n + 1 > SERP_MAX_CALLS_PER_REQUEST:
        raise HTTPException(
            status_code=429,
            detail=f"SerpAPI budget exceeded ({SERP_MAX_CALLS_PER_REQUEST}). Returning cached/approx results."
        )
    _serp_calls.set(n + 1)

def _is_chain(name: str, website: str | None = None) -> bool:
    s = (name or "").lower()
    d = (website or "").lower()
    return any(tok in s or tok in d for tok in KNOWN_CHAINS)

# =========================
# SerpAPI Client
# =========================

SERPAPI_BASE = "https://serpapi.com/search.json"

class SerpAPI:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.client = httpx.Client(timeout=30)

    def _get(self, params: Dict[str, Any]) -> Dict[str, Any]:
        params = {**params, "api_key": self.api_key}
        r = self.client.get(SERPAPI_BASE, params=params)
        if r.status_code != 200:
            raise HTTPException(status_code=502, detail=f"SerpAPI error: {r.text}")
        return r.json()

    def google_local(self, query: str, hl: str = "en", gl: str = "us", num: int = 20) -> Dict[str, Any]:
        _count_serp()
        return self._get({"engine": "google_local", "q": query, "hl": hl, "gl": gl, "num": num})

    def maps_place(self, place_id: str) -> Dict[str, Any]:
        v = _DETAILS_CACHE.get(place_id)
        if v and _fresh(v[0]):
            return v[1]
        _count_serp()
        d = self._get({"engine": "google_maps", "type": "place", "place_id": place_id})
        _DETAILS_CACHE[place_id] = (time.time(), d)
        return d

    def google_maps_reviews(self, place_id: str, sort_by: str = REVIEWS_SORT) -> Dict[str, Any]:
        key = (place_id, sort_by)
        v = _REVIEWS_CACHE.get(key)
        if v and _fresh(v[0]):
            return {"reviews": v[1]}
        _count_serp()
        payload = self._get({"engine": "google_maps_reviews", "place_id": place_id, "sort_by": sort_by})
        reviews = (payload.get("reviews") or [])[:100]  # hard cap
        _REVIEWS_CACHE[key] = (time.time(), reviews)
        return {"reviews": reviews}

serp = SerpAPI(settings.SERPAPI_API_KEY)
