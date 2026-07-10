from __future__ import annotations

import hashlib
import time
from typing import Any

from src.context_budget import compute_input_token_budget


def build_context_diagnostics(payload: dict[str, Any]) -> dict[str, Any]:
    effective_budget = compute_input_token_budget(
        int(payload.get("configured_budget") or 0),
        int(payload.get("context_length") or 0),
        bool(payload.get("explicit_budget")),
    )
    capsules = payload.get("capsules") or []
    included = []
    omitted = []
    for capsule in capsules:
        if not isinstance(capsule, dict):
            continue
        kind = str(capsule.get("kind") or "")
        if capsule.get("included"):
            included.append(kind)
        else:
            omitted.append({"kind": kind, "reason": str(capsule.get("reason") or "not included")})
    contracts = [tool_result_contract(item) for item in payload.get("tool_results") or [] if isinstance(item, dict)]
    return {
        "configured_budget": int(payload.get("configured_budget") or 0),
        "context_length": int(payload.get("context_length") or 0),
        "effective_budget": effective_budget,
        "included_capsules": included,
        "omitted_capsules": omitted,
        "tool_result_contracts": contracts,
        "generated_at": time.time(),
    }


def tool_result_contract(result: dict[str, Any], *, excerpt_chars: int = 512) -> dict[str, Any]:
    output = str(result.get("output") or result.get("stdout") or result.get("content") or "")
    return {
        "tool": str(result.get("tool") or result.get("name") or "unknown"),
        "workspace": result.get("workspace"),
        "mount_id": result.get("mount_id"),
        "timestamp": result.get("timestamp") or time.time(),
        "bounded_excerpt": output[:excerpt_chars],
        "output_hash": hashlib.sha256(output.encode("utf-8", errors="replace")).hexdigest(),
        "truncated": bool(result.get("truncated") or len(output) > excerpt_chars),
    }
