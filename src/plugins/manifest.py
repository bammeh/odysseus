"""Manifest parsing and validation for trusted Odysseus plugins."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


PLUGIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,63}$")
CAPABILITY_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


class PluginManifestError(ValueError):
    """Raised when a plugin manifest is missing required or safe values."""


def _require_str(data: dict[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PluginManifestError(f"Plugin manifest requires non-empty {key}")
    return value.strip()


def _validate_id(value: str, label: str) -> str:
    if not CAPABILITY_ID_RE.fullmatch(value):
        raise PluginManifestError(f"Invalid {label}: {value!r}")
    return value


def _safe_relative_path(root: Path, raw_path: str, label: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise PluginManifestError(f"Plugin manifest requires {label}")
    candidate = (root / raw_path).resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise PluginManifestError(f"Invalid {label}: path must stay inside plugin") from exc
    return candidate


@dataclass(frozen=True)
class PluginPanel:
    plugin_id: str
    id: str
    title: str
    path: str
    icon: str = "plug"
    width: int = 760
    height: int = 520

    @property
    def iframe_url(self) -> str:
        return f"/plugins/{self.plugin_id}/static/{self.path}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "id": self.id,
            "title": self.title,
            "icon": self.icon,
            "width": self.width,
            "height": self.height,
            "iframe_url": self.iframe_url,
        }


@dataclass(frozen=True)
class PluginTool:
    plugin_id: str
    name: str
    description: str
    parameters: dict[str, Any] = field(default_factory=dict)
    read_only: bool = True
    admin_only: bool = False

    @property
    def qualified_name(self) -> str:
        return f"plugin__{self.plugin_id}__{self.name}"

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.qualified_name,
                "description": self.description,
                "parameters": self.parameters or {"type": "object", "properties": {}},
            },
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "qualified_name": self.qualified_name,
            "description": self.description,
            "read_only": self.read_only,
            "admin_only": self.admin_only,
        }


@dataclass(frozen=True)
class PluginManifest:
    root: Path
    id: str
    name: str
    version: str
    entrypoint: Path
    description: str = ""
    author: str = ""
    permissions: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    panels: tuple[PluginPanel, ...] = ()
    tools: tuple[PluginTool, ...] = ()

    @classmethod
    def from_file(cls, path: str | Path) -> "PluginManifest":
        manifest_path = Path(path)
        root = manifest_path.parent.resolve(strict=False)
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PluginManifestError(f"Invalid plugin manifest JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise PluginManifestError("Plugin manifest must be a JSON object")

        plugin_id = _require_str(data, "id")
        if not PLUGIN_ID_RE.fullmatch(plugin_id):
            raise PluginManifestError(f"Invalid plugin id: {plugin_id!r}")

        entrypoint = _safe_relative_path(root, _require_str(data, "entrypoint"), "entrypoint")
        panels = tuple(_parse_panel(root, plugin_id, item) for item in data.get("panels", []) or [])
        tools = tuple(_parse_tool(plugin_id, item) for item in data.get("tools", []) or [])

        return cls(
            root=root,
            id=plugin_id,
            name=_require_str(data, "name"),
            version=_require_str(data, "version"),
            entrypoint=entrypoint,
            description=str(data.get("description") or ""),
            author=str(data.get("author") or ""),
            permissions=tuple(str(item) for item in data.get("permissions", []) or []),
            dependencies=tuple(str(item) for item in data.get("dependencies", []) or []),
            panels=panels,
            tools=tools,
        )

    def as_dict(self, *, enabled_for_user: bool = False) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "description": self.description,
            "author": self.author,
            "permissions": list(self.permissions),
            "dependencies": list(self.dependencies),
            "panels": [panel.as_dict() for panel in self.panels],
            "tools": [tool.as_dict() for tool in self.tools],
            "enabled_for_user": enabled_for_user,
        }


def _parse_panel(root: Path, plugin_id: str, item: Any) -> PluginPanel:
    if not isinstance(item, dict):
        raise PluginManifestError("Plugin panel entries must be objects")
    panel_id = _validate_id(_require_str(item, "id"), "panel id")
    _safe_relative_path(root, _require_str(item, "path"), "panel path")
    return PluginPanel(
        plugin_id=plugin_id,
        id=panel_id,
        title=_require_str(item, "title"),
        path=item["path"].strip().replace("\\", "/"),
        icon=str(item.get("icon") or "plug"),
        width=max(320, int(item.get("width") or 760)),
        height=max(240, int(item.get("height") or 520)),
    )


def _parse_tool(plugin_id: str, item: Any) -> PluginTool:
    if not isinstance(item, dict):
        raise PluginManifestError("Plugin tool entries must be objects")
    tool_name = _validate_id(_require_str(item, "name"), "tool name")
    parameters = item.get("parameters") or {"type": "object", "properties": {}}
    if not isinstance(parameters, dict):
        raise PluginManifestError("Plugin tool parameters must be an object")
    return PluginTool(
        plugin_id=plugin_id,
        name=tool_name,
        description=_require_str(item, "description"),
        parameters=parameters,
        read_only=bool(item.get("read_only", True)),
        admin_only=bool(item.get("admin_only", False)),
    )
