from __future__ import annotations

from fastapi import APIRouter

from src.api.v1.incidents import router as incidents_router

router = APIRouter(prefix="/api/v1")
router.include_router(incidents_router)