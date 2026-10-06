"""FastAPI application entry point.

Run with: uvicorn app.main:app --reload --port 8000
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import disqualified, ingest, pipeline, prospects, qualification_criteria, qualify
from app.routers import eval as eval_router

settings = get_settings()

app = FastAPI(
    title="Prospect Research Agent",
    description="Outbound-prospecting research pipeline backend for Gunadhya.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(ingest.router, prefix="/api")
app.include_router(qualify.router, prefix="/api")
app.include_router(prospects.router, prefix="/api")
app.include_router(disqualified.router, prefix="/api")
app.include_router(eval_router.router, prefix="/api")
app.include_router(pipeline.router, prefix="/api")
app.include_router(qualification_criteria.router, prefix="/api")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
