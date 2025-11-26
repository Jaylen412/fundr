from fastapi import FastAPI
from app.api.v1.router import api_router

app = FastAPI(title="FUNDR API", version="0.1.0")

app.include_router(api_router)
