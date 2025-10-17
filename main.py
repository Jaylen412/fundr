"""
FUNDR — FastAPI + SerpAPI (Google Local/Maps/Reviews) MVP
---------------------------------------------------------
Endpoints:
- GET  /discover?city=&category=&limit=
- GET  /business/{place_id}
- GET  /leaderboard?city=&category=&limit=
- POST /score/recompute   (optional: recompute scores for cached items)

Env:
- SERPAPI_API_KEY=<your key>
- FUNDR_CITYCenterLat, FUNDR_CITYCenterLng (optional hints for maps queries)

Run:
- uvicorn main:app --reload

Notes:
- This is API-only; frontends (React, Notion embeds, Custom GPT actions) can hit these routes.
- Storage is in-memory for MVP; swap for Postgres easily where marked.
"""

from __future__ import annotations
import math
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from pydantic import BaseModel, BaseSettings, Field, validator

# -----------------------------
# Settings & Constants
# -----------------------------

class Settings(BaseSettings):
    SERPAPI_API_KEY: str
    # Optional: city center lat/lng for maps queries (geofencing precision)
    FUNDR_CITYCENTER_LAT: Optional[float] = None
    FUNDR_CITYCENTER_LNG: Optional[float] = None

    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()

# A tiny "known chains" list; expand as needed or load from DB
KNOWN_CHAINS = KNOWN_CHAINS = {
    "starbucks", "mcdonald", "burger king", "wendy", "taco bell", "subway", "chipotle",
    "kfc", "panda express", "five guys", "panera", "chick-fil-a", "domino", "pizza hut",
    "little caesars", "olive garden", "buffalo wild wings", "applebee", "ihop", "denny",
    "cracker barrel", "red lobster", "tgi friday", "texas roadhouse", "outback",
    "jack in the box", "arbys", "sonic", "culver", "raising cane", "whataburger",
    "wingstop", "papa john", "dairy queen", "jimmy john", "jersey mike", "a&w",
    "church's chicken", "bojangles", "shake shack", "carls jr", "hardee", "el pollo loco",
    "waffle house", "nandos", "tim hortons", "blaze pizza", "pita pit",
    
    # Retail & Grocery
    "walmart", "target", "costco", "sams club", "home depot", "lowe", "best buy",
    "walgreens", "cvs", "rite aid", "dollar general", "dollar tree", "family dollar",
    "kroger", "meijer", "safeway", "whole foods", "aldi", "trader joe", "publix",
    "heb", "food lion", "giant eagle", "winn-dixie", "bj's wholesale", "macy", "nordstrom",
    "tj maxx", "marshalls", "ross dress for less", "kohls", "ikea", "bed bath & beyond",
    "staples", "office depot", "office max", "gamestop", "sears", "jcpenney",
    "burlington", "petco", "petsmart", "autozone", "oreilly auto parts", "advance auto",
    
    # Service & Convenience
    "7-eleven", "circle k", "shell", "bp", "chevron", "exxon", "mobil", "valero",
    "speedway", "qt", "sheetz", "casey's", "pilot", "love's travel stop",
    "ups store", "fedex", "usps", "verizon", "att", "t-mobile", "spectrum",
    "xfinity", "comcast", "directv", "enterprise rent a car", "hertz", "avis", "budget",
    "alamo", "national car rental", "u-haul", "homegoods", "bath & body works",
    "victoria's secret", "ulta", "sephora", "foot locker", "finish line", "nike store",
    "adidas store", "old navy", "gap", "banana republic", "h&m", "uniqlo",
    
    # Service Providers
    "ace hardware", "sherwin williams", "jiffy lube", "valvoline", "firestone", "goodyear",
    "maaco", "Meineke", "pep boys", "midas", "h&r block", "jackson hewitt", "liberty tax",
    "great clips", "sport clips", "supercuts", "massage envy", "planet fitness",
    "la fitness", "crunch fitness", "orangetheory", "snap fitness", "yoga six"
}


# -----------------------------
# Data Models
# -----------------------------

class SubScores(BaseModel):
    quality: float = 0.0
    consistency: float = 0.0
    community: float = 0.0
    ops_fit: float = 0.0

class FundrItem(BaseModel):
    place_id: str
    cid: Optional[str] = None
    name: str
    types: List[str] = []
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    price: Optional[str] = None
    open_state: Optional[str] = None
    phone: Optional[str] = None
    website: Optional[str] = None
    hours: Optional[Dict[str, Any]] = None

    rating: Optional[float] = None
    reviews_count: int = 0

    is_chain: bool = False
    flags: List[str] = []
    fundr_score: float = 0.0
    subscores: SubScores = Field(default_factory=SubScores)

class Review(BaseModel):
    place_id: str
    rating: float
    date: Optional[datetime]
    text: str = ""
    likes: Optional[int] = 0
    reviewer_hash: Optional[str] = None

class DiscoverResponse(BaseModel):
    city: str
    category: str
    count: int
    items: List[FundrItem]

class LeaderboardItem(BaseModel):
    place_id: str
    name: str
    fundr_score: float
    subscores: SubScores
    rating: Optional[float]
    reviews_count: int
    price: Optional[str]
    open_state: Optional[str]
    badges: List[str] = []
    why_fund: Optional[str] = None
    top_praise: List[str] = []
    top_fix: List[str] = []

class LeaderboardResponse(BaseModel):
    city: str
    category: str
    updated_at: datetime
    items: List[LeaderboardItem]

# -----------------------------
# Simple In-Memory "DB"
# -----------------------------

BUSINESSES: Dict[str, FundrItem] = {}          # key: place_id
REVIEWS: Dict[str, List[Review]] = {}          # key: place_id
INSIGHTS: Dict[str, Dict[str, Any]] = {}       # key: place_id (why_fund/top_praise/top_fix)
SCORE_LAST_UPDATED: Optional[datetime] = None

# -----------------------------
# SerpAPI Client
# -----------------------------

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

    # Seed discovery (Google Local)
    def google_local(self, query: str, hl: str = "en", gl: str = "us", num: int = 20) -> Dict[str, Any]:
        return self._get({"engine": "google_local", "q": query, "hl": hl, "gl": gl, "num": num})

    # Maps local results (alternate discovery/enrichment)
    def google_maps(self, query: str, ll: Optional[str] = None) -> Dict[str, Any]:
        params = {"engine": "google_maps", "q": query}
        if ll:
            params["ll"] = ll  # format: "@lat,lng,zoomz"
        return self._get(params)

    # Place details
    def maps_place(self, place_id: str) -> Dict[str, Any]:
        return self._get({"engine": "google_maps", "type": "place", "place_id": place_id})

    # Reviews (supports sort_by=newest/most_relevant; use pagination via next_page_token if present)
    def google_maps_reviews(self, place_id: str, sort_by: str = "newest") -> Dict[str, Any]:
        return self._get({"engine": "google_maps_reviews", "place_id": place_id, "sort_by": sort_by})

serp = SerpAPI(settings.SERPAPI_API_KEY)

# -----------------------------
# Utility: Normalization & Heuristics
# -----------------------------

def _is_chain(name: str) -> bool:
    n = name.lower()
    return any(chain in n for chain in KNOWN_CHAINS)

def _log_norm_reviews(count: int, max_expected: int = 2000) -> float:
    # log-scale review volume to 0..1 (cap at max_expected-ish)
    if count <= 0:
        return 0.0
    return min(math.log(1 + count) / math.log(1 + max_expected), 1.0)

def _minmax(v: float, lo: float, hi: float) -> float:
    if hi == lo:
        return 0.0
    return max(0.0, min(1.0, (v - lo) / (hi - lo)))

COMMUNITY_POSITIVE_KEYWORDS = [
    "community", "family-owned", "family owned", "local", "neighborhood",
    "inclusive", "clean", "affordable", "mentorship", "friendly", "kindness"
]
COMMUNITY_NEGATIVE_KEYWORDS = [
    "dirty", "rude", "racist", "unsafe", "pricey", "overpriced"
]

def _community_keyword_score(texts: List[str]) -> float:
    if not texts:
        return 0.0
    pos = sum(sum(k in t.lower() for k in COMMUNITY_POSITIVE_KEYWORDS) for t in texts)
    neg = sum(sum(k in t.lower() for k in COMMUNITY_NEGATIVE_KEYWORDS) for t in texts)
    raw = pos - 1.5 * neg
    # normalize by number of texts
    per = raw / max(1, len(texts))
    # squash to 0..1
    return max(0.0, min(1.0, 0.5 + per / 8.0))

def _recent_cutoff(days: int = 90) -> datetime:
    return datetime.utcnow() - timedelta(days=days)

def _consistency_components(reviews: List[Review]) -> Tuple[float, float]:
    """
    Returns (RecencyPositiveRatio, RatingSlopeNormalized)
    - RecencyPositiveRatio = (% reviews >=4 in last 90d)
    - RatingSlopeNormalized = slope of monthly average ratings (scaled 0..1 where 0.5 is flat)
    """
    if not reviews:
        return (0.0, 0.5)

    # Recency positive
    cutoff = _recent_cutoff()
    recent = [r for r in reviews if r.date and r.date >= cutoff]
    if recent:
        rec_pos = sum(1 for r in recent if (r.rating or 0) >= 4.0) / len(recent)
    else:
        rec_pos = 0.0

    # Monthly slope (simple)
    buckets: Dict[str, List[float]] = {}
    for r in reviews:
        if r.date:
            ym = r.date.strftime("%Y-%m")
            buckets.setdefault(ym, []).append(r.rating or 0)

    if len(buckets) < 2:
        slope_norm = 0.5
    else:
        months = sorted(buckets.keys())
        xs = list(range(len(months)))
        ys = [sum(buckets[m]) / len(buckets[m]) for m in months]
        # simple linear regression slope
        x_mean = sum(xs) / len(xs)
        y_mean = sum(ys) / len(ys)
        num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
        den = sum((x - x_mean) ** 2 for x in xs) or 1.0
        slope = num / den  # ratings per month
        # clamp: -0.2 .. +0.2 mapped to 0..1
        slope_norm = _minmax(slope, -0.2, 0.2)

    return (rec_pos, slope_norm)

def compute_fundr_score(item: FundrItem, reviews: List[Review]) -> Tuple[float, SubScores, List[str]]:
    """
    FUNDR Score = 0.40*Quality + 0.25*Consistency + 0.25*Community + 0.10*OpsFit
    Quality: 0.7*R_norm + 0.3*V_norm
    Consistency: 0.6*Rec90 + 0.4*Slope
    Community: keyword-derived score from review texts
    OpsFit: completeness + open-state reliability
    """
    rating = (item.rating or 0.0)
    R_norm = max(0.0, min(1.0, (rating - 1.0) / 4.0))  # map 1..5 -> 0..1
    V_norm = _log_norm_reviews(item.reviews_count)

    quality = 0.7 * R_norm + 0.3 * V_norm

    rec90, slope = _consistency_components(reviews)
    consistency = 0.6 * rec90 + 0.4 * slope

    texts = [r.text for r in reviews[:250]]  # cap to keep it light
    community = _community_keyword_score(texts)

    ops = 0.0
    ops += 0.3 if item.open_state and item.open_state.lower() == "open" else 0.0
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

# -----------------------------
# Minimal "Insight" (Rule-based; swap to GPT later)
# -----------------------------

def generate_insight(reviews: List[Review]) -> Dict[str, Any]:
    """
    Lightweight, deterministic insight for demo:
    - top_praise/top_fix by keyword frequency
    - why_fund templated sentence
    """
    if not reviews:
        return {"why_fund": "Reliable community favorite with room to grow.", "top_praise": [], "top_fix": []}

    text = " ".join(r.text.lower() for r in reviews[:200])

    praise_vocab = ["friendly", "clean", "authentic", "community", "affordable", "service", "quality", "fresh", "quick"]
    fix_vocab = ["wait", "parking", "pricey", "noisy", "crowded", "slow"]

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

# -----------------------------
# FastAPI App
# -----------------------------

app = FastAPI(title="FUNDR API", version="0.1.0")

def ll_param_from_center(zoom: int = 12) -> Optional[str]:
    if settings.FUNDR_CITYCENTER_LAT is None or settings.FUNDR_CITYCENTER_LNG is None:
        return None
    return f"@{settings.FUNDR_CITYCENTER_LAT},{settings.FUNDR_CITYCENTER_LNG},{zoom}z"

# -----------------------------
# Routes
# -----------------------------

@app.get("/discover", response_model=DiscoverResponse)
def discover(
    city: str = Query(..., description="City, e.g., Detroit"),
    category: str = Query(..., description="Category, e.g., coffee shops"),
    limit: int = Query(20, ge=1, le=50, description="Number of candidates to return"),
    exclude_chains: bool = Query(True, description="Filter out obvious national chains"),
):
    """
    Step 1: Seed candidates via google_local, enrich with google_maps if available.
    """
    query = f"{category} in {city}"

    # google_local
    data_local = serp.google_local(query=query, num=min(limit * 2, 50))
    local_results = data_local.get("local_results", []) or data_local.get("places_results", [])

    items: List[FundrItem] = []
    for r in local_results:
        name = r.get("title") or r.get("name") or ""
        if not name:
            continue

        place_id = r.get("place_id") or r.get("place_id_search") or r.get("place_id_token")
        if not place_id:
            # Some variants may not return place_id; skip for simplicity
            continue

        item = FundrItem(
            place_id=place_id,
            cid=str(r.get("data_cid") or r.get("cid") or "") or None,
            name=name,
            types=r.get("type", []) if isinstance(r.get("type"), list) else [r.get("type")] if r.get("type") else [],
            address=r.get("address"),
            lat=(r.get("gps_coordinates") or {}).get("latitude"),
            lng=(r.get("gps_coordinates") or {}).get("longitude"),
            price=r.get("price"),
            open_state=r.get("open_state") or r.get("open_hours"),
            phone=r.get("phone"),
            website=r.get("website"),
            rating=r.get("rating"),
            reviews_count=int(r.get("reviews") or r.get("reviews_count") or 0),
        )
        item.is_chain = _is_chain(item.name)
        if exclude_chains and item.is_chain:
            continue

        BUSINESSES[item.place_id] = item  # upsert cache
        items.append(item)

        if len(items) >= limit:
            break

    return DiscoverResponse(city=city, category=category, count=len(items), items=items)

@app.get("/business/{place_id}", response_model=FundrItem)
def business_details(place_id: str):
    """
    Step 2: Pull place details + newest & most relevant reviews; compute/update FUNDR score.
    """
    item = BUSINESSES.get(place_id)
    if not item:
        # Try to fetch details regardless (user may jump directly here)
        try:
            p = serp.maps_place(place_id)
        except Exception:
            raise HTTPException(status_code=404, detail="Unknown place_id and fetch failed")
        # Minimal parse (SerpAPI place payloads vary; adjust as needed)
        title = p.get("place_results", {}).get("title") or p.get("title")
        if not title:
            raise HTTPException(status_code=404, detail="Place not found")
        item = FundrItem(place_id=place_id, name=title)
        BUSINESSES[place_id] = item

    # Details enrichment
    detail = serp.maps_place(place_id)
    pr = detail.get("place_results", {}) or detail  # normalize

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
    if "type" in pr:
        t = pr["type"]
        item.types = t if isinstance(t, list) else [t]

    # Reviews (newest + relevant)
    newest = serp.google_maps_reviews(place_id, sort_by="newest").get("reviews", [])
    relevant = serp.google_maps_reviews(place_id, sort_by="most_relevant").get("reviews", [])

    def parse_review(rr: Dict[str, Any]) -> Review:
        # SerpAPI review dates are often like "a month ago", or RFC3339; handle both
        d = rr.get("date") or rr.get("date_utc")
        dt = None
        if isinstance(d, str):
            try:
                dt = datetime.fromisoformat(d.replace("Z", "+00:00"))
            except Exception:
                dt = None  # keep None; consistency calc will adapt
        return Review(
            place_id=place_id,
            rating=float(rr.get("rating", 0)),
            date=dt,
            text=rr.get("snippet") or rr.get("description") or rr.get("text") or "",
            likes=int(rr.get("likes", 0) or 0),
            reviewer_hash=str(rr.get("user_id") or rr.get("contributor_id") or rr.get("review_id") or "") or None,
        )

    parsed = [parse_review(x) for x in (newest + relevant)]
    # de-dup by reviewer_hash+text
    seen = set()
    uniq: List[Review] = []
    for r in parsed:
        key = (r.reviewer_hash, r.text[:80])
        if key not in seen:
            seen.add(key)
            uniq.append(r)

    REVIEWS[place_id] = uniq

    # Compute score + badges
    score, subs, badges = compute_fundr_score(item, uniq)
    item.fundr_score = score
    item.subscores = subs
    item.flags = badges

    # Minimal insights (rule-based)
    INSIGHTS[place_id] = generate_insight(uniq)

    BUSINESSES[place_id] = item
    return item

@app.get("/leaderboard", response_model=LeaderboardResponse)
def leaderboard(
    city: str = Query(...),
    category: str = Query(...),
    limit: int = Query(10, ge=1, le=50),
    require_recent: bool = Query(False, description="Only include places with recent reviews"),
):
    """
    Step 3: Rank by FUNDR score (ensuring details/score exist by fetching business endpoints on demand).
    """
    # Make sure discovered items exist
    discovered = [b for b in BUSINESSES.values()]
    if not discovered:
        # auto discover a small batch if empty
        _ = discover(city=city, category=category, limit=limit * 2, exclude_chains=True)
        discovered = [b for b in BUSINESSES.values()]

    # Ensure each has details & score
    for b in discovered:
        if not b.fundr_score or b.place_id not in REVIEWS:
            try:
                business_details(b.place_id)
            except Exception:
                continue

    # Filter by "recent" if requested
    cutoff = _recent_cutoff()
    def has_recent(pid: str) -> bool:
        return any((r.date and r.date >= cutoff) for r in REVIEWS.get(pid, []))

    ranked = sorted(
        [b for b in BUSINESSES.values() if (not require_recent or has_recent(b.place_id))],
        key=lambda x: x.fundr_score,
        reverse=True
    )[:limit]

    items: List[LeaderboardItem] = []
    for b in ranked:
        ins = INSIGHTS.get(b.place_id, {})
        items.append(LeaderboardItem(
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

    return LeaderboardResponse(
        city=city,
        category=category,
        updated_at=datetime.utcnow(),
        items=items
    )

@app.post("/score/recompute")
def recompute_scores() -> Dict[str, Any]:
    """
    Optional: Recompute FUNDR scores for all cached businesses.
    """
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

# Root
@app.get("/")
def root():
    return {
        "name": "FUNDR API",
        "version": "0.1.0",
        "routes": ["/discover", "/business/{place_id}", "/leaderboard", "/score/recompute"]
    }
