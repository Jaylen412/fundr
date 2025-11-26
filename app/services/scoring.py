import math
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple
from app.models.domain import FundrItem, Review, SubScores

ENRICH_TOP_K = 3

def _log_norm_reviews(count: int, max_expected: int = 2000) -> float:
    if count <= 0:
        return 0.0
    return min(math.log(1 + count) / math.log(1 + max_expected), 1.0)

def _minmax(v: float, lo: float, hi: float) -> float:
    if hi == lo:
        return 0.0
    return max(0.0, min(1.0, (v - lo) / (hi - lo)))

COMMUNITY_POSITIVE_KEYWORDS = [
    "community","family-owned","family owned","local","neighborhood",
    "inclusive","clean","affordable","mentorship","friendly","kindness"
]
COMMUNITY_NEGATIVE_KEYWORDS = [
    "dirty","rude","racist","unsafe","pricey","overpriced"
]

def _community_keyword_score(texts: List[str]) -> float:
    if not texts:
        return 0.0
    pos = sum(sum(k in t.lower() for k in COMMUNITY_POSITIVE_KEYWORDS) for t in texts)
    neg = sum(sum(k in t.lower() for k in COMMUNITY_NEGATIVE_KEYWORDS) for t in texts)
    raw = pos - 1.5 * neg
    per = raw / max(1, len(texts))
    return max(0.0, min(1.0, 0.5 + per / 8.0))

def _recent_cutoff(days: int = 90) -> datetime:
    return datetime.utcnow() - timedelta(days=days)

def _consistency_components(reviews: List[Review]) -> Tuple[float, float]:
    if not reviews:
        return (0.0, 0.5)

    cutoff = _recent_cutoff()
    recent = [r for r in reviews if r.date and r.date >= cutoff]
    rec_pos = (sum(1 for r in recent if (r.rating or 0) >= 4.0) / len(recent)) if recent else 0.0

    buckets: Dict[str, List[float]] = {}
    for r in reviews:
        if r.date:
            ym = r.date.strftime("%Y-%m")
            buckets.setdefault(ym, []).append(r.rating or 0.0)
    if len(buckets) < 2:
        slope_norm = 0.5
    else:
        months = sorted(buckets.keys())
        xs = list(range(len(months)))
        ys = [sum(buckets[m]) / len(buckets[m]) for m in months]
        x_mean = sum(xs) / len(xs)
        y_mean = sum(ys) / len(ys)
        num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
        den = sum((x - x_mean) ** 2 for x in xs) or 1.0
        slope = num / den  # ratings per month
        slope_norm = _minmax(slope, -0.2, 0.2)  # -0.2..+0.2 → 0..1
    return (rec_pos, slope_norm)

def compute_fundr_score(item: FundrItem, reviews: List[Review]) -> Tuple[float, SubScores, List[str]]:
    rating = (item.rating or 0.0)
    R_norm = max(0.0, min(1.0, (rating - 1.0) / 4.0))
    V_norm = _log_norm_reviews(item.reviews_count)

    quality = 0.7 * R_norm + 0.3 * V_norm

    rec90, slope = _consistency_components(reviews)
    consistency = 0.6 * rec90 + 0.4 * slope

    texts = [r.text for r in reviews[:250]]
    community = _community_keyword_score(texts)

    ops = 0.0
    ops += 0.3 if item.open_state and str(item.open_state).lower() == "open" else 0.0
    ops += 0.35 if item.phone else 0.0
    ops += 0.35 if item.website else 0.0
    ops_fit = min(1.0, ops)

    score = 100.0 * (0.40 * quality + 0.25 * consistency + 0.25 * community + 0.10 * ops_fit)

    badges = []
    if rec90 > 0.85 and slope > 0.65 and item.reviews_count >= 50:
        badges.append("Emerging Star")
    if rec90 > 0.90 and abs(slope - 0.5) < 0.10 and item.reviews_count >= 150:
        badges.append("Consistency Ace")
    if community > 0.75 and item.reviews_count >= 100:
        badges.append("Community Favorite")

    subs = SubScores(
        quality=round(quality, 3),
        consistency=round(consistency, 3),
        community=round(community, 3),
        ops_fit=round(ops_fit, 3),
    )
    return round(score, 1), subs, badges

def generate_insight(reviews: List[Review]) -> Dict[str, Any]:
    if not reviews:
        return {"why_fund": "Reliable community favorite with room to grow.", "top_praise": [], "top_fix": []}
    text = " ".join((r.text or "").lower() for r in reviews[:200])
    praise_vocab = ["friendly","clean","authentic","community","affordable","service","quality","fresh","quick"]
    fix_vocab = ["wait","parking","pricey","noisy","crowded","slow"]

    def top_hits(vocab, k=3):
        counts = [(w, text.count(w)) for w in vocab]
        counts.sort(key=lambda x: x[1], reverse=True)
        return [w for w, c in counts if c > 0][:k]

    top_praise = top_hits(praise_vocab)
    top_fix = top_hits(fix_vocab)
    why = "Strong recent customer praise for " + (", ".join(top_praise[:2]) if top_praise else "overall experience")
    if top_fix:
        why += f"; opportunity to improve {top_fix[0]}."
    return {"why_fund": why, "top_praise": top_praise, "top_fix": top_fix}

def _prelim_score(b: FundrItem) -> float:
    R_norm = max(0, min(1, ((b.rating or 0) - 1) / 4))
    V_norm = _log_norm_reviews(b.reviews_count)
    return 0.7 * R_norm + 0.3 * V_norm

# =========================
# Enrichment Logic
# =========================

from app.services.db import BUSINESSES, REVIEWS, INSIGHTS
from app.services.serp import serp, REVIEWS_SORT

def enrich_business_with_reviews(place_id: str):
    item = BUSINESSES.get(place_id) or FundrItem(place_id=place_id, name="Unknown")

    # Details (cached)
    detail = serp.maps_place(place_id)
    pr = detail.get("place_results", {}) or detail
    item.name = pr.get("title") or item.name
    item.address = pr.get("address") or item.address
    item.website = pr.get("website") or item.website
    item.phone = pr.get("phone") or item.phone
    item.rating = pr.get("rating") or item.rating
    item.reviews_count = int(pr.get("reviews") or pr.get("reviews_count") or item.reviews_count or 0)
    item.open_state = pr.get("open_state") or item.open_state
    item.price = pr.get("price") or item.price
    if "gps_coordinates" in pr:
        item.lat = pr["gps_coordinates"].get("latitude", item.lat)
        item.lng = pr["gps_coordinates"].get("longitude", item.lng)

    # Reviews (newest only, 1 page)
    raw = serp.google_maps_reviews(place_id, sort_by=REVIEWS_SORT).get("reviews", [])
    parsed: List[Review] = []
    for rr in raw[:100]:
        d = rr.get("date") or rr.get("date_utc")
        dt = None
        if isinstance(d, str):
            try:
                dt = datetime.fromisoformat(d.replace("Z", "+00:00"))
            except Exception:
                dt = None
        parsed.append(Review(
            place_id=place_id,
            rating=float(rr.get("rating", 0) or 0),
            date=dt,
            text=rr.get("snippet") or rr.get("description") or rr.get("text") or "",
            likes=int(rr.get("likes", 0) or 0),
            reviewer_hash=str(rr.get("user_id") or rr.get("contributor_id") or rr.get("review_id") or "") or None,
        ))
    # Dedup
    seen = set(); uniq: List[Review] = []
    for r in parsed:
        key = (r.reviewer_hash, r.text[:80])
        if key not in seen:
            seen.add(key); uniq.append(r)

    REVIEWS[place_id] = uniq
    score, subs, badges = compute_fundr_score(item, uniq)
    item.fundr_score, item.subscores, item.flags = score, subs, badges
    BUSINESSES[place_id] = item
    INSIGHTS[place_id] = generate_insight(uniq)
