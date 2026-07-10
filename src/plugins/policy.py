"""Plugin policy guards and validation reports."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEPENDENCY_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.-]*(?:\[[A-Za-z0-9_,.-]+\])?(?:\s*(?:==|~=|!=|<=|>=|<|>)\s*[A-Za-z0-9_.!*+-]+)?$"
)
PERMISSION_RE = re.compile(r"^[a-z][a-z0-9_.:-]{1,63}$")

UNSAFE_DEPENDENCY_MARKERS = (
    "://",
    "\\",
    "/",
    ";",
    "|",
    "&",
    "$",
    "`",
    ">",
    "<",
)


@dataclass(frozen=True)
class PluginPolicyIssue:
    code: str
    message: str
    severity: str = "error"

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "severity": self.severity}


def validate_dependency_spec(spec: str) -> str:
    value = str(spec or "").strip()
    if not value:
        raise ValueError("Dependency specs must be non-empty")
    if value.startswith("-") or any(marker in value for marker in UNSAFE_DEPENDENCY_MARKERS):
        raise ValueError(f"Unsafe dependency spec: {value}")
    if not DEPENDENCY_RE.fullmatch(value):
        raise ValueError(f"Unsupported dependency spec: {value}")
    return value


def validate_permission_name(permission: str) -> str:
    value = str(permission or "").strip()
    if not PERMISSION_RE.fullmatch(value):
        raise ValueError(f"Invalid permission name: {value}")
    return value


def _path_exists(root: Path, raw_path: str) -> bool:
    try:
        candidate = (root / raw_path).resolve(strict=False)
        candidate.relative_to(root.resolve(strict=False))
    except Exception:
        return False
    return candidate.exists()


def validate_manifest_policy(manifest: Any) -> dict[str, Any]:
    issues: list[PluginPolicyIssue] = []

    if not manifest.description.strip():
        issues.append(PluginPolicyIssue("manifest.description.missing", "Plugin description is required.", "warning"))

    if not manifest.entrypoint.exists():
        issues.append(PluginPolicyIssue("entrypoint.missing", "Plugin entrypoint file does not exist."))

    for panel in manifest.panels:
        if not _path_exists(manifest.root, panel.path):
            issues.append(PluginPolicyIssue("panel.path.missing", f"Panel {panel.id} points to a missing file."))

    for tool in manifest.tools:
        if not tool.description.strip():
            issues.append(PluginPolicyIssue("tool.description.missing", f"Tool {tool.name} needs a description."))
        params_type = (tool.parameters or {}).get("type")
        if params_type != "object":
            issues.append(PluginPolicyIssue("tool.parameters.type", f"Tool {tool.name} parameters must be a JSON object schema."))

    for permission in manifest.permissions:
        try:
            validate_permission_name(permission)
        except ValueError as exc:
            issues.append(PluginPolicyIssue("permission.invalid", str(exc)))

    for dependency in manifest.dependencies:
        try:
            validate_dependency_spec(dependency)
        except ValueError as exc:
            issues.append(PluginPolicyIssue("dependency.invalid", str(exc)))

    return {
        "valid": not any(issue.severity == "error" for issue in issues),
        "issues": [issue.as_dict() for issue in issues],
        "rules": [
            "plugin ids, capability ids, and permission names must be safe slugs",
            "manifest paths must stay inside the plugin folder",
            "panels must load from plugin static files",
            "tools must use JSON object parameter schemas",
            "dependencies must be package specs, not URLs, paths, editables, or shell-like values",
            "plugin routes are mounted only under /api/plugins/{plugin_id}",
        ],
    }
