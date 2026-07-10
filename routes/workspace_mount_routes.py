from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from src.auth_helpers import effective_user
from src.workspaces.mounts import MountPolicyError, MountRegistry


async def _json(request: Request) -> dict:
    try:
        payload = await request.json()
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _owner(request: Request) -> str:
    return effective_user(request) or "default"


def setup_workspace_mount_routes(registry: MountRegistry | None = None) -> APIRouter:
    registry = registry or MountRegistry()
    router = APIRouter(prefix="/api/workspaces", tags=["workspace-mounts"])

    @router.get("/mounts")
    def list_mounts(request: Request):
        return {"mounts": registry.list_mounts(_owner(request))}

    @router.post("/mounts")
    async def create_mount(request: Request):
        payload = await _json(request)
        try:
            mount = registry.create_mount(
                owner=_owner(request),
                name=payload.get("name", ""),
                root=payload.get("root", ""),
                write_policy=payload.get("write_policy", "read_only"),
                extension_allowlist=payload.get("extension_allowlist") or [],
                max_file_bytes=int(payload.get("max_file_bytes") or 1_000_000),
            )
        except (MountPolicyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"mount": mount}

    @router.post("/mounts/{mount_id}/resolve")
    async def resolve_mount_path(mount_id: str, request: Request):
        payload = await _json(request)
        try:
            path = registry.resolve_access(
                _owner(request),
                mount_id,
                str(payload.get("path") or ""),
                operation=str(payload.get("operation") or "read"),
            )
        except MountPolicyError as exc:
            return {"ok": False, "path": None, "error": str(exc)}
        return {"ok": True, "path": path, "error": ""}

    @router.post("/mounts/{mount_id}/backup")
    async def backup_mount_path(mount_id: str, request: Request):
        payload = await _json(request)
        try:
            backup = registry.backup_before_overwrite(_owner(request), mount_id, str(payload.get("path") or ""))
        except MountPolicyError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"backup": backup}

    return router
