import time
from typing import List
from fastapi import APIRouter, Query

from app.models.domain import DiscoverResponse, FundrItem
from app.services.db import _DISCOVER_CACHE, BUSINESSES, _fresh
from app.services.serp import serp, _serp_calls, _is_chain

router = APIRouter()

@router.get("/discover", response_model=DiscoverResponse)
def discover(
    city: str = Query(..., description="City, e.g., Detroit"),
    category: str = Query(..., description="Category, e.g., coffee shops"),
    limit: int = Query(10, ge=1, le=20, description="Number of candidates to return"),
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
