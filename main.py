# main.py
# FUNDR — FastAPI + SerpAPI (7-call sweet spot: 1 discovery + top-3 [details + newest reviews])

from __future__ import annotations
import math
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import httpx
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from contextvars import ContextVar

# =========================
# Settings
# =========================

class Settings(BaseSettings):
    SERPAPI_API_KEY: str
    FUNDR_CITYCENTER_LAT: float | None = None
    FUNDR_CITYCENTER_LNG: float | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
    )

settings = Settings()

# =========================
# Chain filter (lowercase substrings)
# =========================

KNOWN_CHAINS = {
    "starbucks","mcdonald","burger king","wendy","taco bell","subway","chipotle",
    "kfc","panda express","five guys","panera","chick-fil-a","domino","pizza hut",
    "little caesars","olive garden","buffalo wild wings","applebee","ihop","denny",
    "cracker barrel","red lobster","tgi friday","texas roadhouse","outback",
    "jack in the box","arbys","sonic","culver","raising cane","whataburger",
    "wingstop","papa john","dairy queen","jimmy john","jersey mike","a&w",
    "church's chicken","bojangles","shake shack","carls jr","hardee","el pollo loco",
    "waffle house","walmart","target","costco","sams club","home depot","lowe",
    "best buy","walgreens","cvs","rite aid","dollar general","dollar tree","family dollar",
    "kroger","meijer","safeway","whole foods","aldi","trader joe","publix","heb",
    "food lion","giant eagle","winn-dixie","bj's wholesale","macy","nordstrom","tj maxx",
    "marshalls","ross dress for less","kohls","ikea","bed bath & beyond","staples",
    "office depot","office max","gamestop","sears","jcpenney","burlington","petco",
    "petsmart","autozone","oreilly auto parts","advance auto","7-eleven","circle k",
    "shell","bp","chevron","exxon","mobil","valero","speedway","qt","sheetz","casey's",
    "pilot","love's travel stop","ups store","fedex","usps","verizon","att","t-mobile",
    "spectrum","xfinity","comcast","directv","enterprise rent a car","hertz","avis",
    "budget","alamo","national car rental","u-haul","homegoods","bath & body works",
    "victoria's secret","ulta","sephora","foot locker","finish line","nike store",
    "adidas store","old navy","gap","banana republic","h&m","uniqlo","ace hardware",
    "sherwin williams","jiffy lube","valvoline","firestone","goodyear","maaco",
    "meineke","pep boys","midas","h&r block","jackson hewitt","liberty tax","great clips",
    "sport clips","supercuts","massage envy","planet fitness","la fitness","crunch fitness",
    "orangetheory","snap fitness","yoga six"
}

def _is_chain(name: str, website: str | None = None) -> bool:
    s = (name or "").lower()
    d = (website or "").lower()
    return any(tok in s or tok in d for tok in KNOWN_CHAINS)

# =========================
# Budget & Caches (7-call sweet spot)
# =========================

SERP_MAX_CALLS_PER_REQUEST = 7      # 1 discovery + (top-3 * [details + reviews])
ENRICH_TOP_K = 3
REVIEWS_SORT = "newest"
REVIEW_PAGES = 1                    # (pagination kept simple; single page)
CACHE_TTL_SEC = 6 * 60 * 60         # 6 hours

_serp_calls = ContextVar("serp_calls", default=0)

def _count_serp():
    n = _serp_calls.get()
    if n + 1 > SERP_MAX_CALLS_PER_REQUEST:
        raise HTTPException(
            status_code=429,
            detail=f"SerpAPI budget exceeded ({SERP_MAX_CALLS_PER_REQUEST}). Returning cached/approx results."
        )
    _serp_calls.set(n + 1)

_DISCOVER_CACHE: Dict[tuple, tuple] = {}   # (city, category) -> (ts, items[])
_DETAILS_CACHE: Dict[str, tuple] = {}      # place_id -> (ts, details_dict)
_REVIEWS_CACHE: Dict[tuple, tuple] = {}    # (place_id, REVIEWS_SORT) -> (ts, reviews_list)

def _fresh(ts: float) -> bool:
    return (time.time() - ts) < CACHE_TTL_SEC

# =========================
# Models
# =========================

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

# =========================
# In-memory "DB"
# =========================

BUSINESSES: Dict[str, FundrItem] = {}
REVIEWS: Dict[str, List[Review]] = {}
INSIGHTS: Dict[str, Dict[str, Any]] = {}
SCORE_LAST_UPDATED: Optional[datetime] = None

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

# =========================
# Scoring & Insights
# =========================

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

# =========================
# FastAPI app
# =========================

app = FastAPI(title="FUNDR API", version="0.1.0")

# -------------------------
# Helpers
# -------------------------

def _recent_cutoff(days: int = 90) -> datetime:
    return datetime.utcnow() - timedelta(days=days)

def _prelim_score(b: FundrItem) -> float:
    R_norm = max(0, min(1, ((b.rating or 0) - 1) / 4))
    V_norm = _log_norm_reviews(b.reviews_count)
    return 0.7 * R_norm + 0.3 * V_norm

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

# =========================
# Routes
# =========================

@app.get("/discover", response_model=DiscoverResponse)
def discover(
    city: str = Query(..., description="City, e.g., Detroit"),
    category: str = Query(..., description="Category, e.g., coffee shops"),
    limit: int = Query(5, ge=1, le=20, description="Number of candidates to return"),
    exclude_chains: bool = Query(True, description="Filter out obvious national chains"),
):
    _serp_calls.set(0)  # reset per request

    cache_key = (city.lower(), category.lower())
    v = _DISCOVER_CACHE.get(cache_key)
    if v and _fresh(v[0]):
        items = v[1][:limit]
        return DiscoverResponse(city=city, category=category, count=len(items), items=items)

    data_local = serp.google_local(query=f"{category} in {city}", num=min(limit * 2, 20))
    local_results = data_local.get("local_results", []) or data_local.get("places_results", [])

    items: List[FundrItem] = []
    for r in local_results:
        name = r.get("title") or r.get("name") or ""
        pid = r.get("place_id") or r.get("place_id_search") or r.get("place_id_token")
        if not name or not pid:
            continue
        item = FundrItem(
            place_id=pid,
            cid=str(r.get("data_cid") or r.get("cid") or "") or None,
            name=name,
            types=r.get("type", []) if isinstance(r.get("type"), list) else ([r.get("type")] if r.get("type") else []),
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
        item.is_chain = _is_chain(item.name, item.website)
        if exclude_chains and item.is_chain:
            continue
        BUSINESSES[item.place_id] = item
        items.append(item)
        if len(items) >= limit:
            break

    _DISCOVER_CACHE[cache_key] = (time.time(), items)
    return DiscoverResponse(city=city, category=category, count=len(items), items=items)

@app.get("/business/{place_id}", response_model=FundrItem)
def business_details(place_id: str):
    _serp_calls.set(0)  # each direct call gets its own budget window
    # Always enrich with details+reviews (counts as 2 calls, cached after)
    if place_id not in BUSINESSES:
        BUSINESSES[place_id] = FundrItem(place_id=place_id, name="Unknown")
    enrich_business_with_reviews(place_id)
    return BUSINESSES[place_id]

@app.get("/leaderboard", response_model=LeaderboardResponse)
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

@app.post("/score/recompute")
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

@app.get("/health", status_code=200)
def health():
    """
    Health check endpoint.

    Returns HTTP 200 with {"status": "ok"} if the API is running.
    If the app is down, this endpoint will not respond with HTTP 200.
    """
    return {"status": "ok"}

@app.get("/")
def root():
    return {
        "name": "FUNDR API",
        "version": "0.1.0",
        "routes": ["/discover", "/business/{place_id}", "/leaderboard", "/score/recompute"]
    }
