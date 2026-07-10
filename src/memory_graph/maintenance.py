from __future__ import annotations

import copy
import json
import time
import uuid
from pathlib import Path
from typing import Any

from core.atomic_io import atomic_write_json
from src.constants import DATA_DIR


DEFAULT_MAINTENANCE_FILE = Path(DATA_DIR) / "memory_maintenance.json"


def _new_id() -> str:
    return f"maintenance-{uuid.uuid4().hex[:12]}"


class MemoryMaintenanceStore:
    """File-backed memory maintenance run records.

    The actual summarization/cluster workers can be async later; this store is
    the durable proof ledger they will write to.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or DEFAULT_MAINTENANCE_FILE)
        self._state = self._load()

    def create_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        owner = str(payload.get("owner") or "default")
        evidence = [dict(item) for item in payload.get("evidence") or []]
        proof = dict(payload.get("proof") or {})
        run = {
            "id": _new_id(),
            "owner": owner,
            "kind": str(payload.get("kind") or "maintenance"),
            "status": str(payload.get("status") or "complete"),
            "source_ids": [str(item) for item in payload.get("source_ids") or []],
            "summary": str(payload.get("summary") or ""),
            "evidence": evidence,
            "proof": proof,
            "created_at": time.time(),
            "updated_at": time.time(),
        }
        run["evidence_bound"] = bool(evidence and proof)
        self._state["runs"][run["id"]] = run
        self._save()
        return copy.deepcopy(run)

    def list_runs(self, owner: str | None = None) -> list[dict[str, Any]]:
        owner_key = str(owner or "")
        rows = [
            copy.deepcopy(run)
            for run in self._state["runs"].values()
            if not owner_key or run.get("owner") == owner_key
        ]
        return sorted(rows, key=lambda run: run.get("created_at", 0), reverse=True)

    def _load(self) -> dict[str, Any]:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {"runs": dict(data.get("runs") or {})}
        except (OSError, json.JSONDecodeError):
            pass
        return {"runs": {}}

    def _save(self) -> None:
        atomic_write_json(str(self.path), self._state, indent=2)
