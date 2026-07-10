from __future__ import annotations

import json
from typing import Any


def _bounded_json(value: Any, max_chars: int = 2400) -> str:
    try:
        text = json.dumps(value, ensure_ascii=True, sort_keys=True)
    except TypeError:
        text = json.dumps(str(value), ensure_ascii=True)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 32] + "... [truncated]"


def format_orchestration_context(context: dict[str, Any] | None) -> dict[str, str] | None:
    if not context:
        return None

    identity = dict(context.get("identity") or context.get("agent_identity") or {})
    profile = dict(context.get("agent_profile") or context.get("profile") or {})
    capsules = list(context.get("capsules") or [])

    name = str(profile.get("display_name") or identity.get("profile_id") or "Agent")
    role = str(profile.get("role") or identity.get("role") or "agent")
    run_id = str(context.get("run_id") or identity.get("run_id") or "")
    task_id = str(context.get("task_id") or identity.get("task_id") or "")
    agent_instance_id = str(identity.get("agent_instance_id") or "")
    namespace = str(identity.get("namespace") or "")
    session_id = str(identity.get("session_id") or "")
    scope = identity.get("scope") or context.get("scope") or {}
    instructions = str(profile.get("instructions") or "").strip()

    capsule_lines = []
    for capsule in capsules[:8]:
        kind = capsule.get("kind") or capsule.get("type") or "capsule"
        capsule_lines.append(f"- {kind}: {_bounded_json(capsule, 1200)}")
    if len(capsules) > 8:
        capsule_lines.append(f"- omitted: {len(capsules) - 8} additional capsules")

    lines = [
        "## Orchestration Task Context",
        f"Agent: {name} ({role})",
    ]
    if run_id:
        lines.append(f"Run: {run_id}")
    if task_id:
        lines.append(f"Task: {task_id}")
    if agent_instance_id:
        lines.append(f"Agent instance: {agent_instance_id}")
    if namespace:
        lines.append(f"Namespace: {namespace}")
    if session_id:
        lines.append(f"Session: {session_id}")
    if scope:
        lines.append(f"Scope: {_bounded_json(scope, 1600)}")
    if instructions:
        lines.append(f"Profile instructions: {instructions[:1600]}")
    if capsule_lines:
        lines.append("Capsules:")
        lines.extend(capsule_lines)
    lines.extend(
        [
            "Rules:",
            "- Stay inside the assigned task scope.",
            "- Treat plan graph, handoffs, and evidence as the only shared agent state.",
            "- Preserve evidence for claims, handoffs, and completion decisions.",
        ]
    )
    return {"role": "system", "content": "\n".join(lines)}
