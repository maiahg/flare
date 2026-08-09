from __future__ import annotations

from fastapi import APIRouter

from flare.api.v1.incidents import router as incidents_router
from flare.api.v1.stream import router as stream_router

router = APIRouter(prefix="/api/v1")
router.include_router(incidents_router)
router.include_router(stream_router)