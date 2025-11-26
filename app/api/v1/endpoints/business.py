from fastapi import APIRouter

from app.models.domain import FundrItem
from app.services.db import BUSINESSES
from app.services.serp import _serp_calls
from app.services.scoring import enrich_business_with_reviews

router = APIRouter()

@router.get("/business/{place_id}", response_model=FundrItem)
def business_details(place_id: str):
    _serp_calls.set(0)  # each direct call gets its own budget window
    # Always enrich with details+reviews (counts as 2 calls, cached after)
    if place_id not in BUSINESSES:
        BUSINESSES[place_id] = FundrItem(place_id=place_id, name="Unknown")
    enrich_business_with_reviews(place_id)
    return BUSINESSES[place_id]
