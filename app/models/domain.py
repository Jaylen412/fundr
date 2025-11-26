from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

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
