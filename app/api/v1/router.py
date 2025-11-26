from fastapi import APIRouter

from app.api.v1.endpoints import discovery, business, leaderboard, scoring, health

api_router = APIRouter()

api_router.include_router(discovery.router, tags=["discovery"])
api_router.include_router(business.router, tags=["business"])
api_router.include_router(leaderboard.router, tags=["leaderboard"])
api_router.include_router(scoring.router, tags=["scoring"])
api_router.include_router(health.router, tags=["health"])
