from fastapi import APIRouter

router = APIRouter()

@router.get("/health", status_code=200)
def health():
    """
    Health check endpoint.

    Returns HTTP 200 with {"status": "ok"} if the API is running.
    If the app is down, this endpoint will not respond with HTTP 200.
    """
    return {"status": "ok"}

@router.get("/")
def root():
    return {
        "name": "FUNDR API",
        "version": "0.1.0",
        "routes": ["/discover", "/business/{place_id}", "/leaderboard", "/score/recompute"]
    }
