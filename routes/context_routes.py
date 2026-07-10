from __future__ import annotations

from fastapi import APIRouter, Request

from src.context_diagnostics import build_context_diagnostics


def setup_context_routes() -> APIRouter:
    router = APIRouter(prefix="/api/context", tags=["context"])

    @router.post("/diagnostics")
    async def diagnostics(request: Request):
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        return build_context_diagnostics(payload if isinstance(payload, dict) else {})

    return router
