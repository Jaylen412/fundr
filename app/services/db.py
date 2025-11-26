import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from app.models.domain import FundrItem, Review

# =========================
# Budget & Caches (7-call sweet spot)
# =========================

CACHE_TTL_SEC = 6 * 60 * 60         # 6 hours

_DISCOVER_CACHE: Dict[tuple, tuple] = {}   # (city, category) -> (ts, items[])
_DETAILS_CACHE: Dict[str, tuple] = {}      # place_id -> (ts, details_dict)
_REVIEWS_CACHE: Dict[tuple, tuple] = {}    # (place_id, REVIEWS_SORT) -> (ts, reviews_list)

def _fresh(ts: float) -> bool:
    return (time.time() - ts) < CACHE_TTL_SEC

# =========================
# In-memory "DB"
# =========================

BUSINESSES: Dict[str, FundrItem] = {}
REVIEWS: Dict[str, List[Review]] = {}
INSIGHTS: Dict[str, Dict[str, Any]] = {}
SCORE_LAST_UPDATED: Optional[datetime] = None
