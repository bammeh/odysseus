"""Discovery, user opt-in state, and runtime hooks for Odysseus plugins."""

from __future__ import annotations

import importlib.util
import inspect
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from src.constants import PLUGINS_DIR, PLUGIN_STATE_FILE

from .manifest import PluginManifest, PluginManifestError


class PluginContext:
    """Registration surface exposed to trusted plugin entrypoints."""

    def __init__(self, manifest: PluginManifest) -> None:
        self.manifest = manifest
        self.tool_handlers: dict[str, Callable[..., Any]] = {}
        self.routers: list[Any] = []
        self.context_providers: dict[str, Callable[..., Any]] = {}
        self.jobs: dict[str, Callable[..., Any]] = {}

    def register_tool(self, name: str, handler: Callable[..., Any]) -> None:
        self.tool_handlers[f"plugin__{self.manifest.id}__{name}"] = handler

    def register_router(self, router: Any) -> None:
        self.routers.append(router)

    def register_context_provider(self, name: str, provider: Callable[..., Any]) -> None:
        self.context_providers[name] = provider

    def register_job(self, name: str, job: Callable[..., Any]) -> None:
        self.jobs[name] = job


class PluginManager:
    """Manage trusted admin-installed plugins and per-user visibility."""

    def __init__(self, root: str | Path | None = None, state_file: str | Path | None = None) -> None:
        self.root = Path(root or PLUGINS_DIR)
        self.state_file = Path(state_file or PLUGIN_STATE_FILE)
        self._plugins: dict[str, PluginManifest] = {}
        self._contexts: dict[str, PluginContext] = {}
        self._state = self._load_state()

    def discover(self) -> list[PluginManifest]:
        self.root.mkdir(parents=True, exist_ok=True)
        discovered: dict[str, PluginManifest] = {}
        for manifest_path in sorted(self.root.glob("*/odysseus.plugin.json")):
            manifest = PluginManifest.from_file(manifest_path)
            discovered[manifest.id] = manifest
            self._state.setdefault("plugins", {}).setdefault(manifest.id, {"approved": True})
        self._plugins = discovered
        self._save_state()
        return list(discovered.values())

    def install_local(self, source_path: str | Path) -> PluginManifest:
        source = Path(source_path).expanduser().resolve(strict=False)
        manifest = PluginManifest.from_file(source / "odysseus.plugin.json")
        destination = (self.root / manifest.id).resolve(strict=False)
        root_resolved = self.root.resolve(strict=False)
        try:
            destination.relative_to(root_resolved)
        except ValueError as exc:
            raise PluginManifestError("Plugin install destination escaped plugin root") from exc
        if destination.exists():
            raise FileExistsError(f"Plugin already installed: {manifest.id}")
        for item in source.rglob("*"):
            if item.is_symlink():
                raise PluginManifestError("Plugin installs may not contain symlinks")
        self.root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc"))
        self.discover()
        return self._require_plugin(manifest.id)

    def record_github_candidate(self, repo_url: str, subpath: str = "") -> dict[str, Any]:
        """Record a GitHub plugin candidate for admin audit before download/install."""
        if not isinstance(repo_url, str) or "github.com/" not in repo_url:
            raise PluginManifestError("GitHub plugin source must be a github.com URL")
        candidates = self._state.setdefault("github_candidates", [])
        candidate = {"repo_url": repo_url.strip(), "subpath": str(subpath or "").strip(), "status": "pending_audit"}
        candidates.append(candidate)
        self._save_state()
        return candidate

    def audit_plugins(self) -> list[dict[str, Any]]:
        audits = []
        for manifest in self.list_plugins():
            audits.append(
                {
                    "id": manifest.id,
                    "name": manifest.name,
                    "version": manifest.version,
                    "entrypoint_exists": manifest.entrypoint.exists(),
                    "permissions": list(manifest.permissions),
                    "dependencies": list(manifest.dependencies),
                    "tools": [tool.as_dict() for tool in manifest.tools],
                    "panels": [panel.as_dict() for panel in manifest.panels],
                }
            )
        return audits

    def list_plugins(self) -> list[PluginManifest]:
        return list(self._plugins.values())

    def list_plugins_for_user(self, owner: str | None) -> list[dict[str, Any]]:
        return [
            manifest.as_dict(enabled_for_user=self.is_user_enabled(owner, manifest.id))
            for manifest in self.list_plugins()
        ]

    def set_user_enabled(self, owner: str | None, plugin_id: str, enabled: bool) -> None:
        self._require_plugin(plugin_id)
        user_key = self._owner_key(owner)
        users = self._state.setdefault("users", {})
        enabled_plugins = set(users.setdefault(user_key, {}).get("enabled_plugins", []))
        if enabled:
            enabled_plugins.add(plugin_id)
        else:
            enabled_plugins.discard(plugin_id)
        users[user_key]["enabled_plugins"] = sorted(enabled_plugins)
        self._save_state()

    def is_user_enabled(self, owner: str | None, plugin_id: str) -> bool:
        user_state = self._state.get("users", {}).get(self._owner_key(owner), {})
        return plugin_id in set(user_state.get("enabled_plugins", []))

    def list_panels_for_user(self, owner: str | None) -> list[dict[str, Any]]:
        panels: list[dict[str, Any]] = []
        for manifest in self._enabled_plugins(owner):
            panels.extend(panel.as_dict() for panel in manifest.panels)
        return panels

    def list_tool_schemas_for_user(self, owner: str | None, *, include_admin: bool = True) -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []
        for manifest in self._enabled_plugins(owner):
            for tool in manifest.tools:
                if tool.admin_only and not include_admin:
                    continue
                schemas.append(tool.schema)
        return schemas

    def execute_tool(self, qualified_name: str, args: dict[str, Any] | None, ctx: dict[str, Any] | None = None) -> Any:
        manifest = self._manifest_for_tool(qualified_name)
        owner = (ctx or {}).get("owner")
        if not self.is_user_enabled(owner, manifest.id):
            raise PermissionError(f"Plugin {manifest.id} is not enabled for this user")
        context = self._load_context(manifest)
        handler = context.tool_handlers.get(qualified_name)
        if not handler:
            raise KeyError(f"Plugin tool not registered: {qualified_name}")
        if inspect.iscoroutinefunction(handler):
            raise TypeError("Async plugin tools must be invoked by the async dispatcher")
        return handler(args or {}, ctx or {})

    def get_tool_handlers(self) -> dict[str, Callable[..., Any]]:
        handlers: dict[str, Callable[..., Any]] = {}
        for manifest in self.list_plugins():
            handlers.update(self._load_context(manifest).tool_handlers)
        return handlers

    def build_plugin_routers(self) -> list[tuple[str, Any]]:
        routers: list[tuple[str, Any]] = []
        for manifest in self.list_plugins():
            for router in self._load_context(manifest).routers:
                routers.append((manifest.id, router))
        return routers

    def _enabled_plugins(self, owner: str | None) -> list[PluginManifest]:
        return [manifest for manifest in self.list_plugins() if self.is_user_enabled(owner, manifest.id)]

    def _manifest_for_tool(self, qualified_name: str) -> PluginManifest:
        prefix = "plugin__"
        if not qualified_name.startswith(prefix):
            raise KeyError(f"Not a plugin tool: {qualified_name}")
        plugin_id = qualified_name[len(prefix):].split("__", 1)[0]
        return self._require_plugin(plugin_id)

    def _require_plugin(self, plugin_id: str) -> PluginManifest:
        manifest = self._plugins.get(plugin_id)
        if manifest is None:
            raise KeyError(f"Unknown plugin: {plugin_id}")
        return manifest

    def _load_context(self, manifest: PluginManifest) -> PluginContext:
        if manifest.id in self._contexts:
            return self._contexts[manifest.id]
        if not manifest.entrypoint.exists():
            raise PluginManifestError(f"Plugin entrypoint not found: {manifest.entrypoint}")
        module_name = f"odysseus_plugins.{manifest.id}"
        spec = importlib.util.spec_from_file_location(module_name, manifest.entrypoint)
        if spec is None or spec.loader is None:
            raise PluginManifestError(f"Cannot load plugin entrypoint: {manifest.entrypoint}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        context = PluginContext(manifest)
        register = getattr(module, "register_plugin", None)
        if callable(register):
            register(context)
        self._contexts[manifest.id] = context
        return context

    def _load_state(self) -> dict[str, Any]:
        if not self.state_file.exists():
            return {"plugins": {}, "users": {}}
        try:
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"plugins": {}, "users": {}}
        if not isinstance(data, dict):
            return {"plugins": {}, "users": {}}
        data.setdefault("plugins", {})
        data.setdefault("users", {})
        return data

    def _save_state(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self.state_file.name}.",
            suffix=".tmp",
            dir=str(self.state_file.parent),
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self._state, handle, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self.state_file)
        finally:
            try:
                os.unlink(tmp_name)
            except FileNotFoundError:
                pass

    @staticmethod
    def _owner_key(owner: str | None) -> str:
        return str(owner or "default")
