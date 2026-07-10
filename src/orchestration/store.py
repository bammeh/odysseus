from __future__ import annotations

import copy
import json
import time
import uuid
from pathlib import Path
from typing import Any

from core.atomic_io import atomic_write_json
from src.constants import DATA_DIR


DEFAULT_STORE = Path(DATA_DIR) / "orchestration.json"


PROFILE_TEMPLATES: list[dict[str, Any]] = [
    {
        "id": "implementer",
        "display_name": "Implementer",
        "role": "implementer",
        "capabilities": ["implement", "edit", "test"],
        "instructions": "Implement scoped tasks and attach evidence.",
    },
    {
        "id": "reviewer",
        "display_name": "Reviewer",
        "role": "reviewer",
        "capabilities": ["review", "reflect", "verify"],
        "instructions": "Review scoped work for drift, regressions, and missing evidence.",
    },
    {
        "id": "integrator",
        "display_name": "Integrator",
        "role": "integrator",
        "capabilities": ["integrate", "release", "coordinate"],
        "instructions": "Integrate accepted work and prepare release evidence.",
    },
    {
        "id": "researcher",
        "display_name": "Researcher",
        "role": "researcher",
        "capabilities": ["research", "summarize", "cite"],
        "instructions": "Gather evidence and summarize findings with source links.",
    },
    {
        "id": "planner",
        "display_name": "Planner",
        "role": "planner",
        "capabilities": ["plan", "decompose", "sequence"],
        "instructions": "Break goals into sequenced, scoped implementation tasks.",
    },
    {
        "id": "tester",
        "display_name": "Tester",
        "role": "tester",
        "capabilities": ["test", "reproduce", "verify"],
        "instructions": "Exercise behavior and report exact verification evidence.",
    },
]


BUILTIN_PROFILES: list[dict[str, Any]] = [
    {
        "id": "builtin-alice",
        "owner": "system",
        "display_name": "Alice",
        "role": "implementer",
        "instructions": "Alice implements one scoped task at a time and attaches concrete evidence.",
        "default_tools": ["get_workspace", "grep", "glob", "ls", "read_file", "edit_file"],
        "capabilities": ["implement", "edit", "test"],
        "scope_policy": {"workspace_required": True},
        "automation_hints": {"handoff_to": "reviewer"},
        "review_expectations": {"requires_evidence": True},
        "enabled": True,
        "builtin": True,
        "read_only": True,
    },
    {
        "id": "builtin-bob",
        "owner": "system",
        "display_name": "Bob",
        "role": "reviewer",
        "instructions": "Bob reviews scope, evidence, and drift before work can be accepted.",
        "default_tools": ["get_workspace", "grep", "glob", "ls", "read_file"],
        "capabilities": ["review", "reflect", "verify"],
        "scope_policy": {"workspace_required": False},
        "automation_hints": {"handoff_to": "integrator"},
        "review_expectations": {"requires_evidence": True, "requires_scope_check": True},
        "enabled": True,
        "builtin": True,
        "read_only": True,
    },
    {
        "id": "builtin-charlie",
        "owner": "system",
        "display_name": "Charlie",
        "role": "integrator",
        "instructions": "Charlie integrates accepted work, updates state, and prepares release evidence.",
        "default_tools": ["get_workspace", "grep", "glob", "ls", "read_file"],
        "capabilities": ["integrate", "release", "coordinate"],
        "scope_policy": {"workspace_required": False},
        "automation_hints": {"requires_quality_gates": True},
        "review_expectations": {"requires_evidence": True},
        "enabled": True,
        "builtin": True,
        "read_only": True,
    },
]


def _now() -> float:
    return time.time()


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def _owner_key(owner: str | None) -> str:
    return str(owner or "default")


class OrchestrationError(ValueError):
    """Raised when orchestration state violates a user-facing rule."""


class OrchestrationStore:
    """File-backed v1 store for profiles, teams, runs, handoffs, and gates."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or DEFAULT_STORE)
        self._state = self._load()
        self._seed_defaults()

    def templates(self) -> list[dict[str, Any]]:
        return copy.deepcopy(PROFILE_TEMPLATES)

    def list_profiles(self, owner: str | None = None) -> list[dict[str, Any]]:
        owner_key = _owner_key(owner)
        profiles = []
        for profile in self._state["profiles"].values():
            if profile.get("builtin") or profile.get("owner") == owner_key:
                profiles.append(copy.deepcopy(profile))
        return sorted(profiles, key=lambda p: (not p.get("builtin", False), p.get("display_name", "").lower()))

    def create_profile(self, owner: str | None, payload: dict[str, Any]) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        display_name = str(payload.get("display_name") or "").strip()
        if not display_name:
            raise OrchestrationError("display_name is required")
        self._ensure_unique_profile_name(owner_key, display_name)
        profile = {
            "id": _new_id("profile"),
            "owner": owner_key,
            "display_name": display_name,
            "role": str(payload.get("role") or "implementer").strip() or "implementer",
            "instructions": str(payload.get("instructions") or ""),
            "default_tools": list(payload.get("default_tools") or []),
            "capabilities": list(payload.get("capabilities") or []),
            "scope_policy": dict(payload.get("scope_policy") or {}),
            "automation_hints": dict(payload.get("automation_hints") or {}),
            "review_expectations": dict(payload.get("review_expectations") or {}),
            "enabled": bool(payload.get("enabled", True)),
            "builtin": False,
            "read_only": False,
            "created_at": _now(),
            "updated_at": _now(),
        }
        self._state["profiles"][profile["id"]] = profile
        self._save()
        return copy.deepcopy(profile)

    def update_profile(self, owner: str | None, profile_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        profile = self._require_profile(profile_id, owner)
        if profile.get("read_only"):
            raise OrchestrationError("Built-in profiles are read-only; duplicate them to customize.")
        if "display_name" in payload:
            display_name = str(payload.get("display_name") or "").strip()
            if not display_name:
                raise OrchestrationError("display_name is required")
            self._ensure_unique_profile_name(profile["owner"], display_name, exclude_id=profile_id)
            profile["display_name"] = display_name
        for key in (
            "role",
            "instructions",
            "default_tools",
            "capabilities",
            "scope_policy",
            "automation_hints",
            "review_expectations",
            "enabled",
        ):
            if key in payload:
                profile[key] = copy.deepcopy(payload[key])
        profile["updated_at"] = _now()
        self._save()
        return copy.deepcopy(profile)

    def duplicate_profile(self, owner: str | None, profile_id: str, display_name: str | None = None) -> dict[str, Any]:
        source = self._require_profile(profile_id, owner, allow_builtin=True)
        clone = copy.deepcopy(source)
        clone["id"] = _new_id("profile")
        clone["owner"] = _owner_key(owner)
        clone["display_name"] = str(display_name or f"{source['display_name']} Copy").strip()
        self._ensure_unique_profile_name(clone["owner"], clone["display_name"])
        clone["enabled"] = True
        clone["builtin"] = False
        clone["read_only"] = False
        clone["created_at"] = _now()
        clone["updated_at"] = _now()
        self._state["profiles"][clone["id"]] = clone
        self._save()
        return copy.deepcopy(clone)

    def delete_profile(self, owner: str | None, profile_id: str) -> None:
        profile = self._require_profile(profile_id, owner)
        if profile.get("read_only"):
            raise OrchestrationError("Built-in profiles are read-only; duplicate them to customize.")
        self._state["profiles"].pop(profile_id, None)
        self._save()

    def list_teams(self, owner: str | None = None) -> list[dict[str, Any]]:
        owner_key = _owner_key(owner)
        teams = []
        for team in self._state["teams"].values():
            if team.get("builtin") or team.get("owner") == owner_key:
                teams.append(copy.deepcopy(team))
        return sorted(teams, key=lambda t: (not t.get("builtin", False), t.get("name", "").lower()))

    def create_team(self, owner: str | None, payload: dict[str, Any]) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        name = str(payload.get("name") or "").strip()
        if not name:
            raise OrchestrationError("name is required")
        members = [dict(member) for member in payload.get("members") or []]
        for member in members:
            self._require_profile(str(member.get("profile_id") or ""), owner_key, allow_builtin=True)
            member.setdefault("slot", self._state["profiles"][member["profile_id"]]["role"])
        team = {
            "id": _new_id("team"),
            "owner": owner_key,
            "name": name,
            "description": str(payload.get("description") or ""),
            "members": members,
            "routing_rules": dict(payload.get("routing_rules") or {}),
            "enabled": bool(payload.get("enabled", True)),
            "builtin": False,
            "created_at": _now(),
            "updated_at": _now(),
        }
        self._state["teams"][team["id"]] = team
        self._save()
        return copy.deepcopy(team)

    def create_run(self, owner: str | None, payload: dict[str, Any]) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        goal = str(payload.get("goal") or "").strip()
        if not goal:
            raise OrchestrationError("goal is required")
        team = self._require_team(str(payload.get("team_id") or "default"), owner_key)
        tasks = []
        for role in ("implementer", "reviewer", "integrator"):
            profile_id = self._profile_for_role(team, role)
            if not profile_id:
                continue
            profile = self._require_enabled_profile(profile_id, owner_key)
            tasks.append(
                {
                    "id": _new_id("task"),
                    "title": f"{role.title()} task",
                    "role": role,
                    "status": "pending",
                    "profile_id": profile["id"],
                    "agent_instance_id": _new_id("agent"),
                    "namespace": f"{role}:{uuid.uuid4().hex[:8]}",
                    "evidence": [],
                    "quality_gate_status": "unknown",
                }
            )
        if not tasks:
            raise OrchestrationError("team has no enabled profiles to receive work")
        run = {
            "id": _new_id("run"),
            "owner": owner_key,
            "goal": goal,
            "team_id": team["id"],
            "status": "running",
            "heartbeat": "running",
            "plan_graph": {"tasks": tasks, "dependencies": []},
            "created_at": _now(),
            "updated_at": _now(),
        }
        self._state["runs"][run["id"]] = run
        self._save()
        return copy.deepcopy(run)

    def list_runs(self, owner: str | None = None) -> list[dict[str, Any]]:
        owner_key = _owner_key(owner)
        return [
            copy.deepcopy(run)
            for run in self._state["runs"].values()
            if run.get("owner") == owner_key
        ]

    def create_handoff(self, owner: str | None, payload: dict[str, Any]) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        run = self._require_run(str(payload.get("run_id") or ""), owner_key)
        handoff = {
            "id": _new_id("handoff"),
            "owner": owner_key,
            "run_id": run["id"],
            "from_profile_id": str(payload.get("from_profile_id") or ""),
            "to_profile_id": str(payload.get("to_profile_id") or ""),
            "summary": str(payload.get("summary") or ""),
            "scope": dict(payload.get("scope") or {}),
            "evidence": list(payload.get("evidence") or []),
            "status": "open",
            "created_at": _now(),
        }
        self._state["handoffs"][handoff["id"]] = handoff
        self._save()
        return copy.deepcopy(handoff)

    def evaluate_quality_gate(self, owner: str | None, payload: dict[str, Any]) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        self._require_run(str(payload.get("run_id") or ""), owner_key)
        evidence = payload.get("evidence") or []
        changed_files = set(payload.get("changed_files") or [])
        allowed_files = set(payload.get("allowed_files") or [])
        gates = [
            {"name": "evidence_freshness", "status": "pass" if evidence else "fail"},
            {"name": "scope_guard", "status": "pass" if changed_files <= allowed_files else "fail"},
            {"name": "context_budget", "status": "pass" if (payload.get("context_budget") or {}).get("proof") else "fail"},
            {"name": "mount_policy", "status": "pass" if (payload.get("mount_policy") or {}).get("respected") else "fail"},
        ]
        result = {
            "id": _new_id("gate"),
            "owner": owner_key,
            "run_id": str(payload.get("run_id") or ""),
            "task_id": str(payload.get("task_id") or ""),
            "passed": all(gate["status"] == "pass" for gate in gates),
            "gates": gates,
            "created_at": _now(),
        }
        self._state["quality_gates"][result["id"]] = result
        self._save()
        return copy.deepcopy(result)

    def _load(self) -> dict[str, Any]:
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return {
                        "profiles": dict(data.get("profiles") or {}),
                        "teams": dict(data.get("teams") or {}),
                        "runs": dict(data.get("runs") or {}),
                        "handoffs": dict(data.get("handoffs") or {}),
                        "quality_gates": dict(data.get("quality_gates") or {}),
                    }
        except (OSError, json.JSONDecodeError):
            pass
        return {"profiles": {}, "teams": {}, "runs": {}, "handoffs": {}, "quality_gates": {}}

    def _save(self) -> None:
        atomic_write_json(str(self.path), self._state, indent=2)

    def _seed_defaults(self) -> None:
        changed = False
        for profile in BUILTIN_PROFILES:
            if profile["id"] not in self._state["profiles"]:
                seeded = copy.deepcopy(profile)
                seeded.setdefault("created_at", _now())
                seeded.setdefault("updated_at", _now())
                self._state["profiles"][seeded["id"]] = seeded
                changed = True
        if "default" not in self._state["teams"]:
            self._state["teams"]["default"] = {
                "id": "default",
                "owner": "system",
                "name": "Alice / Bob / Charlie",
                "description": "Default starter team for scoped implementation, review, and integration.",
                "members": [
                    {"profile_id": "builtin-alice", "slot": "implementer"},
                    {"profile_id": "builtin-bob", "slot": "reviewer"},
                    {"profile_id": "builtin-charlie", "slot": "integrator"},
                ],
                "routing_rules": {
                    "implementer": ["implement", "edit", "test"],
                    "reviewer": ["review", "verify"],
                    "integrator": ["integrate", "release"],
                },
                "enabled": True,
                "builtin": True,
                "created_at": _now(),
                "updated_at": _now(),
            }
            changed = True
        if changed:
            self._save()

    def _ensure_unique_profile_name(self, owner: str, display_name: str, exclude_id: str | None = None) -> None:
        target = display_name.casefold()
        for profile_id, profile in self._state["profiles"].items():
            if profile_id == exclude_id:
                continue
            if profile.get("owner") == owner and str(profile.get("display_name", "")).casefold() == target:
                raise OrchestrationError("profile display_name must be unique per owner")

    def _require_profile(self, profile_id: str, owner: str | None, *, allow_builtin: bool = True) -> dict[str, Any]:
        profile = self._state["profiles"].get(str(profile_id or ""))
        if not profile:
            raise OrchestrationError("unknown profile")
        owner_key = _owner_key(owner)
        if profile.get("builtin") and allow_builtin:
            return profile
        if profile.get("owner") != owner_key:
            raise OrchestrationError("unknown profile")
        return profile

    def _require_enabled_profile(self, profile_id: str | None, owner: str | None) -> dict[str, Any]:
        profile = self._require_profile(str(profile_id or ""), owner, allow_builtin=True)
        if not profile.get("enabled", True):
            raise OrchestrationError(f"profile {profile.get('display_name') or profile.get('id')} is disabled")
        return profile

    def _require_team(self, team_id: str, owner: str) -> dict[str, Any]:
        team = self._state["teams"].get(team_id)
        if not team:
            raise OrchestrationError("unknown team")
        if not team.get("builtin") and team.get("owner") != owner:
            raise OrchestrationError("unknown team")
        if not team.get("enabled", True):
            raise OrchestrationError("team is disabled")
        return team

    def _require_run(self, run_id: str, owner: str) -> dict[str, Any]:
        run = self._state["runs"].get(run_id)
        if not run or run.get("owner") != owner:
            raise OrchestrationError("unknown run")
        return run

    def _profile_for_role(self, team: dict[str, Any], role: str) -> str | None:
        for member in team.get("members") or []:
            if member.get("slot") == role:
                return member.get("profile_id")
        for member in team.get("members") or []:
            profile = self._state["profiles"].get(member.get("profile_id"))
            if profile and profile.get("role") == role:
                return profile["id"]
        if team.get("members"):
            return team["members"][0].get("profile_id")
        return None
