from __future__ import annotations

import json
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from core.atomic_io import atomic_write_json
from src.constants import DATA_DIR
from src.tool_execution import _is_sensitive_path, vet_workspace


DEFAULT_MOUNTS_FILE = Path(DATA_DIR) / "workspace_mounts.json"


class MountPolicyError(ValueError):
    """Raised when a mount or file access violates mount policy."""


def _owner_key(owner: str | None) -> str:
    return str(owner or "default")


def _new_id() -> str:
    return f"mount-{uuid.uuid4().hex[:12]}"


def _is_filesystem_root(path: str) -> bool:
    parent = os.path.dirname(path)
    return not parent or parent == path


class MountRegistry:
    """Owner-scoped v1 registry for external directory mounts."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or DEFAULT_MOUNTS_FILE)
        self._state = self._load()

    def create_mount(
        self,
        *,
        owner: str | None,
        name: str,
        root: str,
        write_policy: str = "read_only",
        extension_allowlist: list[str] | None = None,
        max_file_bytes: int = 1_000_000,
    ) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        name = str(name or "").strip()
        if not name:
            raise MountPolicyError("name is required")
        root_real = self._validate_mount_root(root)
        if write_policy not in {"read_only", "backup"}:
            raise MountPolicyError("write_policy must be read_only or backup")
        mount = {
            "id": _new_id(),
            "owner": owner_key,
            "name": name,
            "root": root_real,
            "write_policy": write_policy,
            "extension_allowlist": sorted({self._normalize_ext(ext) for ext in (extension_allowlist or []) if ext}),
            "max_file_bytes": int(max_file_bytes or 0),
            "enabled": True,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        self._state["mounts"][mount["id"]] = mount
        self._audit(owner_key, mount["id"], "mount_created", root_real, True)
        self._save()
        return dict(mount)

    def list_mounts(self, owner: str | None) -> list[dict[str, Any]]:
        owner_key = _owner_key(owner)
        return [
            dict(mount)
            for mount in self._state["mounts"].values()
            if mount.get("owner") == owner_key
        ]

    def resolve_access(self, owner: str | None, mount_id: str, relative_path: str, *, operation: str) -> str:
        owner_key = _owner_key(owner)
        mount = self._require_mount(owner_key, mount_id)
        if operation not in {"read", "write", "edit"}:
            raise MountPolicyError("operation must be read, write, or edit")
        root = os.path.realpath(mount["root"])
        raw = str(relative_path or "").strip()
        if not raw:
            raise MountPolicyError("path is required")
        candidate = raw if os.path.isabs(raw) else os.path.join(root, raw)
        resolved = os.path.realpath(candidate)
        try:
            if resolved != root and os.path.commonpath([os.path.normcase(resolved), os.path.normcase(root)]) != os.path.normcase(root):
                raise ValueError
        except ValueError:
            self._audit(owner_key, mount_id, f"{operation}_denied", resolved, False, "outside mount")
            raise MountPolicyError("path is outside the mount")
        if _is_sensitive_path(resolved):
            self._audit(owner_key, mount_id, f"{operation}_denied", resolved, False, "sensitive path")
            raise MountPolicyError("path is sensitive")
        self._check_extension(mount, resolved)
        if operation in {"write", "edit"} and mount.get("write_policy") != "backup":
            self._audit(owner_key, mount_id, f"{operation}_denied", resolved, False, "read-only mount")
            raise MountPolicyError("mount is read-only")
        if os.path.exists(resolved):
            self._check_size(mount, resolved)
        self._audit(owner_key, mount_id, operation, resolved, True)
        self._save()
        return resolved

    def backup_before_overwrite(self, owner: str | None, mount_id: str, relative_path: str) -> dict[str, Any] | None:
        owner_key = _owner_key(owner)
        source = self.resolve_access(owner_key, mount_id, relative_path, operation="edit")
        if not os.path.exists(source):
            return None
        backup_dir = self.path.parent / "mount_backups" / mount_id
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"{Path(source).name}.{int(time.time() * 1000)}.bak"
        shutil.copy2(source, backup_path)
        record = {
            "id": f"backup-{uuid.uuid4().hex[:12]}",
            "owner": owner_key,
            "mount_id": mount_id,
            "original_path": source,
            "backup_path": str(backup_path),
            "created_at": time.time(),
        }
        self._state.setdefault("backups", []).append(record)
        self._audit(owner_key, mount_id, "backup_created", source, True)
        self._save()
        return dict(record)

    def _load(self) -> dict[str, Any]:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {
                        "mounts": dict(data.get("mounts") or {}),
                        "audit": list(data.get("audit") or []),
                        "backups": list(data.get("backups") or []),
                    }
        except (OSError, json.JSONDecodeError):
            pass
        return {"mounts": {}, "audit": [], "backups": []}

    def _save(self) -> None:
        atomic_write_json(str(self.path), self._state, indent=2)

    def _validate_mount_root(self, root: str) -> str:
        resolved = vet_workspace(str(root or ""))
        if not resolved:
            raise MountPolicyError("mount root is not selectable")
        if _is_filesystem_root(resolved):
            raise MountPolicyError("mount root cannot be a filesystem root")
        return resolved

    def _require_mount(self, owner: str, mount_id: str) -> dict[str, Any]:
        mount = self._state["mounts"].get(str(mount_id or ""))
        if not mount or mount.get("owner") != owner:
            raise MountPolicyError("unknown mount")
        if not mount.get("enabled", True):
            raise MountPolicyError("mount is disabled")
        return mount

    def _check_extension(self, mount: dict[str, Any], path: str) -> None:
        allowlist = set(mount.get("extension_allowlist") or [])
        if not allowlist:
            return
        ext = Path(path).suffix.casefold()
        if ext not in allowlist:
            raise MountPolicyError(f"extension {ext or '(none)'} is not allowed")

    def _check_size(self, mount: dict[str, Any], path: str) -> None:
        max_bytes = int(mount.get("max_file_bytes") or 0)
        if max_bytes <= 0:
            return
        try:
            size = os.path.getsize(path)
        except OSError:
            return
        if size > max_bytes:
            raise MountPolicyError(f"file exceeds mount size limit ({size} > {max_bytes})")

    def _audit(self, owner: str, mount_id: str, action: str, path: str, allowed: bool, reason: str = "") -> None:
        self._state.setdefault("audit", []).append(
            {
                "id": f"audit-{uuid.uuid4().hex[:12]}",
                "owner": owner,
                "mount_id": mount_id,
                "action": action,
                "path": path,
                "allowed": allowed,
                "reason": reason,
                "created_at": time.time(),
            }
        )

    @staticmethod
    def _normalize_ext(ext: str) -> str:
        value = str(ext or "").strip().casefold()
        return value if value.startswith(".") else f".{value}"
