"""Routes for trusted plugin management and per-user plugin surfaces."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.staticfiles import StaticFiles

from core.middleware import require_admin
from src.plugins.manifest import PluginManifestError
from src.plugins.manager import PluginManager


def _request_owner(request: Request) -> str:
    current_user = getattr(request.state, "current_user", None)
    if current_user:
        return str(current_user)
    user = getattr(request.state, "user", None)
    if isinstance(user, dict) and user.get("username"):
        return str(user["username"])
    if isinstance(user, str) and user:
        return user
    return request.headers.get("x-test-user") or "default"


def _mount_plugin_surfaces(request: Request, plugin_manager: PluginManager, plugin_id: str) -> None:
    plugin = next((item for item in plugin_manager.list_plugins() if item.id == plugin_id), None)
    if not plugin:
        return
    static_path = f"/plugins/{plugin.id}/static"
    if not any(getattr(route, "path", None) == static_path for route in request.app.routes):
        request.app.mount(
            static_path,
            StaticFiles(directory=str(plugin.root)),
            name=f"plugin-{plugin.id}-static",
        )
    mounted = getattr(request.app.state, "mounted_plugin_app_routes", set())
    if plugin.id not in mounted:
        for routed_plugin_id, plugin_router in plugin_manager.build_plugin_routers(plugin.id):
            request.app.include_router(plugin_router, prefix=f"/api/plugins/{routed_plugin_id}")
        mounted.add(plugin.id)
        request.app.state.mounted_plugin_app_routes = mounted


def setup_plugin_routes(plugin_manager: PluginManager) -> APIRouter:
    router = APIRouter(prefix="/api/plugins", tags=["plugins"])

    @router.get("")
    def list_plugins(request: Request):
        return plugin_manager.list_plugins_for_user(_request_owner(request))

    @router.get("/panels")
    def list_panels(request: Request):
        return plugin_manager.list_panels_for_user(_request_owner(request))

    @router.get("/tools")
    def list_tools(request: Request):
        return plugin_manager.list_tool_schemas_for_user(_request_owner(request))

    @router.get("/audit")
    def audit_plugins(request: Request):
        require_admin(request)
        return plugin_manager.audit_plugins()

    @router.get("/{plugin_id}/validation")
    def validation_report(plugin_id: str, request: Request):
        require_admin(request)
        try:
            return plugin_manager.validation_report(plugin_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.post("/install/local")
    async def install_local(request: Request):
        require_admin(request)
        payload = await request.json()
        try:
            manifest = plugin_manager.install_local(payload.get("path", ""))
        except (PluginManifestError, FileExistsError, OSError) as exc:
            raise HTTPException(400, str(exc)) from exc
        _mount_plugin_surfaces(request, plugin_manager, manifest.id)
        return manifest.as_dict(enabled_for_user=False)

    @router.post("/install/github")
    async def install_github_candidate(request: Request):
        require_admin(request)
        payload = await request.json()
        try:
            return plugin_manager.record_github_candidate(payload.get("repo_url", ""), payload.get("subpath", ""))
        except PluginManifestError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/{plugin_id}/enable")
    async def set_enabled(plugin_id: str, request: Request):
        try:
            payload: dict[str, Any] = await request.json()
        except Exception:
            payload = {}
        try:
            plugin_manager.set_user_enabled(_request_owner(request), plugin_id, bool(payload.get("enabled")))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"id": plugin_id, "enabled": plugin_manager.is_user_enabled(_request_owner(request), plugin_id)}

    @router.post("/{plugin_id}/global-enable")
    async def set_global_enabled(plugin_id: str, request: Request):
        require_admin(request)
        try:
            payload: dict[str, Any] = await request.json()
        except Exception:
            payload = {}
        try:
            plugin_manager.set_plugin_globally_enabled(plugin_id, bool(payload.get("enabled")))
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        return {"id": plugin_id, "enabled": plugin_manager.is_plugin_globally_enabled(plugin_id)}

    return router


def setup_plugin_app_routes(plugin_manager: PluginManager) -> APIRouter:
    router = APIRouter(tags=["plugin-apps"])
    for plugin_id, plugin_router in plugin_manager.build_plugin_routers():
        router.include_router(plugin_router, prefix=f"/api/plugins/{plugin_id}")
    return router
