from datetime import datetime
from typing import Any, Dict
from fastapi import APIRouter

from app.services.db import BUSINESSES, REVIEWS, SCORE_LAST_UPDATED
from app.services.scoring import compute_fundr_score

router = APIRouter()

@router.post("/score/recompute")
def recompute_scores() -> Dict[str, Any]:
    global SCORE_LAST_UPDATED
    updated = 0
    for pid, item in BUSINESSES.items():
        reviews = REVIEWS.get(pid, [])
        if not reviews:
            continue
        score, subs, badges = compute_fundr_score(item, reviews)
        item.fundr_score = score
        item.subscores = subs
        item.flags = badges
        BUSINESSES[pid] = item
        updated += 1
    SCORE_LAST_UPDATED = datetime.utcnow()
    return {"updated": updated, "as_of": SCORE_LAST_UPDATED.isoformat()}
