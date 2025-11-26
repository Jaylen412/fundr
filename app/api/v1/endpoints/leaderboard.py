from datetime import datetime
from typing import List
from fastapi import APIRouter, HTTPException

from app.models.domain import FundrItem, LeaderboardItem, LeaderboardResponse
from app.services.db import _DISCOVER_CACHE, BUSINESSES, REVIEWS, INSIGHTS, _fresh
from app.services.serp import _serp_calls
from app.services.scoring import _prelim_score, _recent_cutoff, enrich_business_with_reviews, ENRICH_TOP_K
from app.api.v1.endpoints.discovery import discover

router = APIRouter()

@router.get("/leaderboard", response_model=LeaderboardResponse)
def leaderboard(
    city: str,
    category: str,
    limit: int = 10,
    require_recent: bool = False,
):
    _serp_calls.set(0)

    # Use cached discover or call once
    cached = _DISCOVER_CACHE.get((city.lower(), category.lower()))
    if cached and _fresh(cached[0]):
        items = cached[1]
    else:
        items = discover(city=city, category=category, limit=max(limit * 2, 10), exclude_chains=True).items

    # Prelim ranking (no extra calls)
    topk = sorted(items, key=_prelim_score, reverse=True)[:ENRICH_TOP_K]

    # Enrich top-3 only (each: details + reviews)
    for b in topk:
        if b.place_id not in REVIEWS:
            try:
                enrich_business_with_reviews(b.place_id)
            except HTTPException:
                # On budget hit or upstream error, skip enrichment; we'll return approx
                pass

    # Assemble final list
    scored: List[FundrItem] = []
    for b in items:
        if b.place_id in REVIEWS and REVIEWS[b.place_id]:
            scored.append(BUSINESSES[b.place_id])
        else:
            approx_quality = _prelim_score(b)
            approx_fundr = round(100 * (0.40 * approx_quality + 0.10 * 0.8), 1)  # small OpsFit credit
            tmp = b.model_copy(deep=True)
            tmp.fundr_score = approx_fundr
            scored.append(tmp)

    if require_recent:
        cutoff = _recent_cutoff()
        scored = [x for x in scored if any((r.date and r.date >= cutoff) for r in REVIEWS.get(x.place_id, []))]

    ranked = sorted(scored, key=lambda x: x.fundr_score, reverse=True)[:limit]

    out: List[LeaderboardItem] = []
    for b in ranked:
        ins = INSIGHTS.get(b.place_id, {})
        out.append(LeaderboardItem(
            place_id=b.place_id,
            name=b.name,
            fundr_score=b.fundr_score,
            subscores=b.subscores,
            rating=b.rating,
            reviews_count=b.reviews_count,
            price=b.price,
            open_state=b.open_state,
            badges=b.flags,
            why_fund=ins.get("why_fund"),
            top_praise=ins.get("top_praise", []),
            top_fix=ins.get("top_fix", []),
        ))

    return LeaderboardResponse(city=city, category=category, updated_at=datetime.utcnow(), items=out)
