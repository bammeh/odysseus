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
            "from_task_id": str(payload.get("from_task_id") or ""),
            "to_task_id": str(payload.get("to_task_id") or ""),
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

    def start_task(self, owner: str | None, run_id: str, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        run = self._require_run(run_id, owner_key)
        task = self._require_task(run, task_id)
        self._require_enabled_profile(task.get("profile_id"), owner_key)
        if task.get("status") not in {"pending", "blocked", "rejected"}:
            raise OrchestrationError(f"invalid transition from {task.get('status')} to running")
        task["scope"] = copy.deepcopy(payload.get("scope") or task.get("scope") or {})
        if "session_id" in payload:
            task["session_id"] = str(payload.get("session_id") or "")
        task["status"] = "running"
        task["heartbeat"] = "running"
        task["started_at"] = task.get("started_at") or _now()
        self._append_status(task, "running", payload.get("notes", ""))
        task["agent_identity"] = self._agent_identity(run, task)
        run["heartbeat"] = "running"
        run["updated_at"] = _now()
        self._save()
        return copy.deepcopy(task)

    def attach_task_session(self, owner: str | None, run_id: str, task_id: str, session_id: str) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        run = self._require_run(run_id, owner_key)
        task = self._require_task(run, task_id)
        task["session_id"] = str(session_id or "")
        task["agent_identity"] = self._agent_identity(run, task)
        task["updated_at"] = _now()
        run["updated_at"] = _now()
        self._save()
        return copy.deepcopy(task)

    def transition_task(self, owner: str | None, run_id: str, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        run = self._require_run(run_id, owner_key)
        task = self._require_task(run, task_id)
        new_status = str(payload.get("status") or "").strip()
        if not new_status:
            raise OrchestrationError("status is required")
        current = str(task.get("status") or "pending")
        allowed = {
            "pending": {"running", "failed"},
            "running": {"blocked", "failed", "needs_review"},
            "blocked": {"running", "failed"},
            "needs_review": {"accepted", "rejected", "running"},
            "rejected": {"running", "failed"},
            "accepted": {"integrated"},
            "integrated": set(),
            "failed": {"running"},
        }
        if new_status not in allowed.get(current, set()):
            raise OrchestrationError(f"invalid transition from {current} to {new_status}")
        task["status"] = new_status
        task["heartbeat"] = str(payload.get("heartbeat") or self._heartbeat_for_status(new_status))
        if payload.get("evidence"):
            task.setdefault("evidence", []).extend(copy.deepcopy(payload.get("evidence") or []))
        self._append_status(task, new_status, payload.get("notes", ""))
        task["agent_identity"] = self._agent_identity(run, task)
        run["heartbeat"] = self._run_heartbeat(run)
        run["updated_at"] = _now()
        self._save()
        return copy.deepcopy(task)

    def task_context(self, owner: str | None, run_id: str, task_id: str) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        run = self._require_run(run_id, owner_key)
        task = self._require_task(run, task_id)
        profile = self._require_profile(task.get("profile_id", ""), owner_key, allow_builtin=True)
        handoffs = [
            copy.deepcopy(handoff)
            for handoff in self._state["handoffs"].values()
            if handoff.get("run_id") == run_id
            and (handoff.get("to_task_id") == task_id or handoff.get("from_task_id") == task_id)
        ]
        capsules = [
            {"kind": "agent_profile", "profile": copy.deepcopy(profile), "tokens": 1, "included": True},
            {
                "kind": "plan_graph_state",
                "run_id": run_id,
                "goal": run.get("goal", ""),
                "tasks": copy.deepcopy(run.get("plan_graph", {}).get("tasks", [])),
                "tokens": 1,
                "included": True,
            },
            {"kind": "handoff_summary", "handoffs": handoffs, "tokens": 1, "included": True},
        ]
        if task.get("scope"):
            capsules.append({"kind": "mount_policy", "scope": copy.deepcopy(task.get("scope")), "tokens": 1, "included": True})
        return {"agent_identity": self._agent_identity(run, task), "capsules": capsules}

    def review_handoff(self, owner: str | None, handoff_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        handoff = self._require_handoff(handoff_id, owner_key)
        run = self._require_run(handoff["run_id"], owner_key)
        decision = str(payload.get("decision") or "").strip()
        if decision not in {"accepted", "rejected"}:
            raise OrchestrationError("decision must be accepted or rejected")
        handoff["status"] = decision
        handoff["review"] = {
            "decision": decision,
            "reviewer_profile_id": str(payload.get("reviewer_profile_id") or ""),
            "notes": str(payload.get("notes") or ""),
            "evidence": list(payload.get("evidence") or []),
            "created_at": _now(),
        }
        from_task = self._find_task(run, handoff.get("from_task_id"))
        to_task = self._find_task(run, handoff.get("to_task_id"))
        if decision == "accepted":
            if from_task:
                from_task["status"] = "accepted"
                from_task["heartbeat"] = "idle"
                self._append_status(from_task, "accepted", payload.get("notes", ""))
            if to_task:
                to_task["status"] = "running"
                to_task["heartbeat"] = "running"
                to_task["agent_identity"] = self._agent_identity(run, to_task)
                self._append_status(to_task, "running", "handoff accepted")
        else:
            if from_task:
                from_task["status"] = "rejected"
                from_task["heartbeat"] = "blocked"
                self._append_status(from_task, "rejected", payload.get("notes", ""))
        run["heartbeat"] = self._run_heartbeat(run)
        run["updated_at"] = _now()
        self._save()
        return {"handoff": copy.deepcopy(handoff), "run": copy.deepcopy(run)}

    def evaluate_quality_gate(self, owner: str | None, payload: dict[str, Any]) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        run = self._require_run(str(payload.get("run_id") or ""), owner_key)
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
        task = self._find_task(run, result["task_id"])
        if task:
            task["quality_gate_status"] = "passed" if result["passed"] else "failed"
        self._save()
        return copy.deepcopy(result)

    def reflector_review(self, owner: str | None, run_id: str, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        run = self._require_run(run_id, owner_key)
        task = self._require_task(run, task_id)
        reviewer_profile_id = str(payload.get("reviewer_profile_id") or "")
        if reviewer_profile_id:
            self._require_enabled_profile(reviewer_profile_id, owner_key)

        changed_files = [str(path) for path in payload.get("changed_files") or []]
        allowed_files = [
            str(path)
            for path in (payload.get("allowed_files") or task.get("scope", {}).get("files") or [])
        ]
        outside_scope = self._outside_scope(changed_files, allowed_files)

        handoff = None
        handoff_id = str(payload.get("handoff_id") or "")
        if handoff_id:
            handoff = self._require_handoff(handoff_id, owner_key)
            if handoff.get("run_id") != run_id:
                raise OrchestrationError("handoff does not belong to run")
            if task_id not in {handoff.get("from_task_id"), handoff.get("to_task_id")}:
                raise OrchestrationError("handoff does not reference task")
        handoff_evidence = list((handoff or {}).get("evidence") or payload.get("handoff_evidence") or [])

        contracts = [dict(contract) for contract in payload.get("tool_result_contracts") or []]
        invalid_contracts = [
            contract
            for contract in contracts
            if not contract.get("tool") or not contract.get("output_hash") or contract.get("truncated") is True
        ]
        gates = [
            {
                "name": "scope_guard",
                "status": "pass" if not outside_scope else "fail",
                "details": {"changed_files": changed_files, "allowed_files": allowed_files, "outside_scope": outside_scope},
            },
            {
                "name": "handoff_evidence",
                "status": "pass" if handoff_evidence else "fail",
                "details": {"handoff_id": handoff_id, "evidence_count": len(handoff_evidence)},
            },
            {
                "name": "tool_result_contracts",
                "status": "pass" if contracts and not invalid_contracts else "fail",
                "details": {"contract_count": len(contracts), "invalid_contracts": invalid_contracts},
            },
            {
                "name": "context_budget",
                "status": "pass" if (payload.get("context_budget") or {}).get("proof") else "fail",
                "details": copy.deepcopy(payload.get("context_budget") or {}),
            },
            {
                "name": "mount_policy",
                "status": "pass" if (payload.get("mount_policy") or {}).get("respected") else "fail",
                "details": copy.deepcopy(payload.get("mount_policy") or {}),
            },
        ]
        review = {
            "id": _new_id("reflector"),
            "owner": owner_key,
            "run_id": run_id,
            "task_id": task_id,
            "reviewer_profile_id": reviewer_profile_id,
            "system_owned": True,
            "passed": all(gate["status"] == "pass" for gate in gates),
            "gates": gates,
            "notes": str(payload.get("notes") or ""),
            "created_at": _now(),
        }
        self._state["reflector_reviews"][review["id"]] = review
        self._state["quality_gates"][review["id"]] = {
            "id": review["id"],
            "owner": owner_key,
            "run_id": run_id,
            "task_id": task_id,
            "kind": "reflector_review",
            "passed": review["passed"],
            "gates": copy.deepcopy(gates),
            "created_at": review["created_at"],
        }
        task["quality_gate_status"] = "passed" if review["passed"] else "failed"
        self._append_status(task, "reflector_passed" if review["passed"] else "reflector_failed", review["notes"])
        run["updated_at"] = _now()
        self._save()
        return copy.deepcopy(review)

    def snapshot(self, owner: str | None, run_id: str) -> dict[str, Any]:
        owner_key = _owner_key(owner)
        run = self._require_run(run_id, owner_key)
        tasks = run.get("plan_graph", {}).get("tasks", [])
        jobs_by_task: dict[str, list[dict[str, Any]]] = {}
        try:
            from src import bg_jobs

            for job in bg_jobs.refresh().values():
                if job.get("run_id") != run_id:
                    continue
                task_id = str(job.get("task_id") or "")
                jobs_by_task.setdefault(task_id, []).append(
                    {
                        "id": job.get("id"),
                        "session_id": job.get("session_id"),
                        "run_id": job.get("run_id"),
                        "task_id": task_id,
                        "profile_id": job.get("profile_id"),
                        "agent_instance_id": job.get("agent_instance_id"),
                        "status": "killed" if job.get("killed") else job.get("status"),
                        "cwd": job.get("cwd"),
                        "command": job.get("command"),
                        "started_at": job.get("started_at"),
                        "ended_at": job.get("ended_at"),
                        "exit_code": job.get("exit_code"),
                    }
                )
        except Exception:
            jobs_by_task = {}
        agents = []
        for task in tasks:
            profile = self._state["profiles"].get(task.get("profile_id"))
            agents.append(
                {
                    "task_id": task.get("id"),
                    "agent_identity": self._agent_identity(run, task),
                    "profile": copy.deepcopy(profile or {}),
                    "jobs": copy.deepcopy(jobs_by_task.get(str(task.get("id") or ""), [])),
                }
            )
        return {
            "run": copy.deepcopy(run),
            "active_tasks": [copy.deepcopy(task) for task in tasks if task.get("status") in {"running", "needs_review"}],
            "blocked_tasks": [copy.deepcopy(task) for task in tasks if task.get("status") == "blocked"],
            "agents": agents,
            "handoffs": [
                copy.deepcopy(handoff)
                for handoff in self._state["handoffs"].values()
                if handoff.get("run_id") == run_id
            ],
            "quality_gates": [
                copy.deepcopy(gate)
                for gate in self._state["quality_gates"].values()
                if gate.get("run_id") == run_id
            ],
            "reflector_reviews": [
                copy.deepcopy(review)
                for review in self._state["reflector_reviews"].values()
                if review.get("run_id") == run_id
            ],
        }

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
                        "reflector_reviews": dict(data.get("reflector_reviews") or {}),
                    }
        except (OSError, json.JSONDecodeError):
            pass
        return {
            "profiles": {},
            "teams": {},
            "runs": {},
            "handoffs": {},
            "quality_gates": {},
            "reflector_reviews": {},
        }

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

    def _require_handoff(self, handoff_id: str, owner: str) -> dict[str, Any]:
        handoff = self._state["handoffs"].get(str(handoff_id or ""))
        if not handoff or handoff.get("owner") != owner:
            raise OrchestrationError("unknown handoff")
        return handoff

    def _require_task(self, run: dict[str, Any], task_id: str) -> dict[str, Any]:
        task = self._find_task(run, task_id)
        if not task:
            raise OrchestrationError("unknown task")
        return task

    @staticmethod
    def _find_task(run: dict[str, Any], task_id: str | None) -> dict[str, Any] | None:
        for task in run.get("plan_graph", {}).get("tasks", []):
            if task.get("id") == task_id:
                return task
        return None

    @staticmethod
    def _outside_scope(changed_files: list[str], allowed_files: list[str]) -> list[str]:
        if not allowed_files:
            return list(changed_files)
        normalized_allowed = [path.replace("\\", "/").strip() for path in allowed_files if str(path).strip()]
        outside: list[str] = []
        for changed in changed_files:
            normalized = changed.replace("\\", "/").strip()
            if not any(
                normalized == allowed
                or (allowed.endswith("/") and normalized.startswith(allowed))
                for allowed in normalized_allowed
            ):
                outside.append(changed)
        return outside

    @staticmethod
    def _heartbeat_for_status(status: str) -> str:
        return {
            "running": "running",
            "blocked": "blocked",
            "needs_review": "needs_review",
            "failed": "failed",
            "integrated": "complete",
        }.get(status, "idle")

    def _run_heartbeat(self, run: dict[str, Any]) -> str:
        statuses = {task.get("status") for task in run.get("plan_graph", {}).get("tasks", [])}
        if "failed" in statuses:
            return "failed"
        if "blocked" in statuses:
            return "blocked"
        if "needs_review" in statuses:
            return "needs_review"
        if "running" in statuses:
            return "running"
        if statuses and statuses <= {"integrated", "accepted"}:
            return "complete"
        return "idle"

    @staticmethod
    def _append_status(task: dict[str, Any], status: str, notes: Any = "") -> None:
        task.setdefault("status_history", []).append(
            {"status": status, "notes": str(notes or ""), "timestamp": _now()}
        )
        task["updated_at"] = _now()

    def _agent_identity(self, run: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
        return {
            "owner": run.get("owner", "default"),
            "profile_id": task.get("profile_id", ""),
            "agent_instance_id": task.get("agent_instance_id", ""),
            "role": task.get("role", ""),
            "namespace": task.get("namespace", ""),
            "scope": copy.deepcopy(task.get("scope") or {}),
            "run_id": run.get("id", ""),
            "task_id": task.get("id", ""),
            "session_id": task.get("session_id", ""),
        }

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
