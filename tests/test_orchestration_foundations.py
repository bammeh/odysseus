import os
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest


def _client(router):
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_default_profiles_are_seeded_and_builtin_profiles_are_protected(tmp_path):
    from routes.orchestration_routes import setup_orchestration_routes
    from src.orchestration.store import OrchestrationStore

    store = OrchestrationStore(tmp_path / "orchestration.json")
    client = _client(setup_orchestration_routes(store))

    profiles = client.get("/api/orchestration/profiles").json()["profiles"]
    by_name = {profile["display_name"]: profile for profile in profiles}
    assert {"Alice", "Bob", "Charlie"}.issubset(by_name)
    assert by_name["Alice"]["builtin"] is True
    assert by_name["Alice"]["read_only"] is True
    assert by_name["Alice"]["role"] == "implementer"
    assert by_name["Bob"]["role"] == "reviewer"
    assert by_name["Charlie"]["role"] == "integrator"

    response = client.patch(
        f"/api/orchestration/profiles/{by_name['Alice']['id']}",
        json={"display_name": "Alicia"},
    )
    assert response.status_code == 400
    assert "read-only" in response.json()["detail"]


def test_custom_profile_crud_duplicate_and_disable(tmp_path):
    from routes.orchestration_routes import setup_orchestration_routes
    from src.orchestration.store import OrchestrationStore

    store = OrchestrationStore(tmp_path / "orchestration.json")
    client = _client(setup_orchestration_routes(store))

    created = client.post(
        "/api/orchestration/profiles",
        json={
            "display_name": "Dana",
            "role": "tester",
            "instructions": "Verify implementation evidence.",
            "default_tools": ["read_file", "grep"],
            "capabilities": ["test", "review"],
            "scope_policy": {"workspace_required": True, "allowed_mounts": ["mount-a"]},
            "automation_hints": {"delegate_when": "tests are missing"},
            "review_expectations": {"requires_evidence": True},
        },
    ).json()["profile"]

    assert created["owner"] == "default"
    assert created["display_name"] == "Dana"
    assert created["builtin"] is False
    assert created["scope_policy"]["allowed_mounts"] == ["mount-a"]

    updated = client.patch(
        f"/api/orchestration/profiles/{created['id']}",
        json={"enabled": False, "instructions": "Only inspect test evidence."},
    ).json()["profile"]
    assert updated["enabled"] is False
    assert updated["instructions"] == "Only inspect test evidence."

    duplicate = client.post(
        f"/api/orchestration/profiles/{created['id']}/duplicate",
        json={"display_name": "Dana Copy"},
    ).json()["profile"]
    assert duplicate["id"] != created["id"]
    assert duplicate["display_name"] == "Dana Copy"
    assert duplicate["enabled"] is True

    deleted = client.delete(f"/api/orchestration/profiles/{created['id']}")
    assert deleted.status_code == 200
    remaining_ids = {p["id"] for p in client.get("/api/orchestration/profiles").json()["profiles"]}
    assert created["id"] not in remaining_ids
    assert duplicate["id"] in remaining_ids


def test_profile_templates_and_team_cards_support_custom_agents(tmp_path):
    from routes.orchestration_routes import setup_orchestration_routes
    from src.orchestration.store import OrchestrationStore

    store = OrchestrationStore(tmp_path / "orchestration.json")
    client = _client(setup_orchestration_routes(store))

    templates = client.get("/api/orchestration/profile-templates").json()["templates"]
    assert {"implementer", "reviewer", "integrator", "researcher", "planner", "tester"} <= {
        template["role"] for template in templates
    }

    profile = client.post(
        "/api/orchestration/profiles",
        json={"display_name": "Riley", "role": "planner", "capabilities": ["plan"]},
    ).json()["profile"]
    team = client.post(
        "/api/orchestration/teams",
        json={
            "name": "Planning Team",
            "description": "A custom planning team",
            "members": [{"profile_id": profile["id"], "slot": "planner"}],
            "routing_rules": {"planner": ["plan"]},
        },
    ).json()["team"]

    assert team["name"] == "Planning Team"
    assert team["members"][0]["profile_id"] == profile["id"]

    teams = client.get("/api/orchestration/teams").json()["teams"]
    default = next(team for team in teams if team["builtin"])
    assert default["name"] == "Alice / Bob / Charlie"
    assert {member["slot"] for member in default["members"]} == {"implementer", "reviewer", "integrator"}


def test_runs_handoffs_and_quality_gates_are_generic_over_profiles(tmp_path):
    from routes.orchestration_routes import setup_orchestration_routes
    from src.orchestration.store import OrchestrationStore

    store = OrchestrationStore(tmp_path / "orchestration.json")
    client = _client(setup_orchestration_routes(store))

    run = client.post(
        "/api/orchestration/runs",
        json={"goal": "Add a safe mount manager", "team_id": "default"},
    ).json()["run"]
    assert run["goal"] == "Add a safe mount manager"
    assert run["status"] == "running"
    assert [task["role"] for task in run["plan_graph"]["tasks"]] == [
        "implementer",
        "reviewer",
        "integrator",
    ]
    assert all(task["profile_id"] for task in run["plan_graph"]["tasks"])

    handoff = client.post(
        "/api/orchestration/handoffs",
        json={
            "run_id": run["id"],
            "from_profile_id": run["plan_graph"]["tasks"][0]["profile_id"],
            "to_profile_id": run["plan_graph"]["tasks"][1]["profile_id"],
            "summary": "Implementation ready for scoped review.",
            "scope": {"files": ["src/workspaces/mounts.py"]},
            "evidence": [{"kind": "test", "ref": "tests/test_mounts.py::test_policy"}],
        },
    ).json()["handoff"]
    assert handoff["run_id"] == run["id"]
    assert handoff["evidence"][0]["kind"] == "test"

    gates = client.post(
        "/api/orchestration/quality-gates",
        json={
            "run_id": run["id"],
            "task_id": run["plan_graph"]["tasks"][1]["id"],
            "evidence": [{"kind": "test", "fresh": True}],
            "changed_files": ["src/workspaces/mounts.py"],
            "allowed_files": ["src/workspaces/mounts.py", "tests/test_mounts.py"],
            "context_budget": {"proof": True},
            "mount_policy": {"respected": True},
        },
    ).json()["result"]

    assert gates["passed"] is True
    assert {gate["name"]: gate["status"] for gate in gates["gates"]}["scope_guard"] == "pass"


def test_task_start_attach_session_and_context_capsules(tmp_path):
    from routes.orchestration_routes import setup_orchestration_routes
    from src.orchestration.store import OrchestrationStore

    store = OrchestrationStore(tmp_path / "orchestration.json")
    client = _client(setup_orchestration_routes(store))

    run = client.post(
        "/api/orchestration/runs",
        json={"goal": "Implement task lifecycle", "team_id": "default"},
    ).json()["run"]
    task = run["plan_graph"]["tasks"][0]

    started = client.post(
        f"/api/orchestration/runs/{run['id']}/tasks/{task['id']}/start",
        json={"session_id": "session-alice", "scope": {"files": ["src/orchestration/store.py"]}},
    ).json()["task"]

    assert started["status"] == "running"
    assert started["heartbeat"] == "running"
    assert started["session_id"] == "session-alice"
    assert started["scope"]["files"] == ["src/orchestration/store.py"]
    assert started["agent_identity"] == {
        "owner": "default",
        "profile_id": started["profile_id"],
        "agent_instance_id": started["agent_instance_id"],
        "role": "implementer",
        "namespace": started["namespace"],
        "scope": {"files": ["src/orchestration/store.py"]},
        "run_id": run["id"],
        "task_id": task["id"],
        "session_id": "session-alice",
    }

    attached = client.post(
        f"/api/orchestration/runs/{run['id']}/tasks/{task['id']}/attach-session",
        json={"session_id": "session-alice-2"},
    ).json()["task"]
    assert attached["session_id"] == "session-alice-2"
    assert attached["agent_identity"]["session_id"] == "session-alice-2"

    context = client.get(
        f"/api/orchestration/runs/{run['id']}/tasks/{task['id']}/context"
    ).json()
    capsule_kinds = {capsule["kind"] for capsule in context["capsules"]}
    assert {"agent_profile", "plan_graph_state", "handoff_summary"}.issubset(capsule_kinds)
    profile_capsule = next(c for c in context["capsules"] if c["kind"] == "agent_profile")
    assert profile_capsule["profile"]["display_name"] == "Alice"
    assert context["agent_identity"]["session_id"] == "session-alice-2"


def test_task_state_machine_rejects_invalid_transitions_and_updates_heartbeat(tmp_path):
    from routes.orchestration_routes import setup_orchestration_routes
    from src.orchestration.store import OrchestrationStore

    store = OrchestrationStore(tmp_path / "orchestration.json")
    client = _client(setup_orchestration_routes(store))

    run = client.post("/api/orchestration/runs", json={"goal": "State machine"}).json()["run"]
    task = run["plan_graph"]["tasks"][0]

    invalid = client.post(
        f"/api/orchestration/runs/{run['id']}/tasks/{task['id']}/transition",
        json={"status": "integrated"},
    )
    assert invalid.status_code == 400
    assert "invalid transition" in invalid.json()["detail"]

    running = client.post(
        f"/api/orchestration/runs/{run['id']}/tasks/{task['id']}/start",
        json={"session_id": "s1"},
    ).json()["task"]
    assert running["status"] == "running"

    blocked = client.post(
        f"/api/orchestration/runs/{run['id']}/tasks/{task['id']}/transition",
        json={"status": "blocked", "heartbeat": "blocked", "notes": "Needs user input"},
    ).json()["task"]
    assert blocked["status"] == "blocked"
    assert blocked["heartbeat"] == "blocked"
    assert blocked["status_history"][-1]["notes"] == "Needs user input"

    resumed = client.post(
        f"/api/orchestration/runs/{run['id']}/tasks/{task['id']}/transition",
        json={"status": "running", "heartbeat": "running"},
    ).json()["task"]
    assert resumed["status"] == "running"
    assert resumed["heartbeat"] == "running"

    review = client.post(
        f"/api/orchestration/runs/{run['id']}/tasks/{task['id']}/transition",
        json={"status": "needs_review", "evidence": [{"kind": "test", "ref": "tests pass"}]},
    ).json()["task"]
    assert review["status"] == "needs_review"
    assert review["heartbeat"] == "needs_review"
    assert review["evidence"] == [{"kind": "test", "ref": "tests pass"}]


def test_handoff_review_accepts_or_rejects_with_evidence(tmp_path):
    from routes.orchestration_routes import setup_orchestration_routes
    from src.orchestration.store import OrchestrationStore

    store = OrchestrationStore(tmp_path / "orchestration.json")
    client = _client(setup_orchestration_routes(store))

    run = client.post("/api/orchestration/runs", json={"goal": "Review handoff"}).json()["run"]
    implementer, reviewer = run["plan_graph"]["tasks"][:2]
    client.post(f"/api/orchestration/runs/{run['id']}/tasks/{implementer['id']}/start", json={})
    client.post(
        f"/api/orchestration/runs/{run['id']}/tasks/{implementer['id']}/transition",
        json={"status": "needs_review", "evidence": [{"kind": "diff", "ref": "abc123"}]},
    )
    handoff = client.post(
        "/api/orchestration/handoffs",
        json={
            "run_id": run["id"],
            "from_task_id": implementer["id"],
            "to_task_id": reviewer["id"],
            "from_profile_id": implementer["profile_id"],
            "to_profile_id": reviewer["profile_id"],
            "summary": "Ready for review",
            "evidence": [{"kind": "diff", "ref": "abc123"}],
        },
    ).json()["handoff"]

    accepted = client.post(
        f"/api/orchestration/handoffs/{handoff['id']}/review",
        json={
            "decision": "accepted",
            "reviewer_profile_id": reviewer["profile_id"],
            "notes": "Evidence matches scope.",
            "evidence": [{"kind": "review", "ref": "bob-approved"}],
        },
    ).json()

    assert accepted["handoff"]["status"] == "accepted"
    assert accepted["handoff"]["review"]["decision"] == "accepted"
    tasks = {task["id"]: task for task in accepted["run"]["plan_graph"]["tasks"]}
    assert tasks[implementer["id"]]["status"] == "accepted"
    assert tasks[reviewer["id"]]["status"] == "running"


def test_reflector_review_detects_scope_and_evidence_drift(tmp_path):
    from routes.orchestration_routes import setup_orchestration_routes
    from src.orchestration.store import OrchestrationStore

    store = OrchestrationStore(tmp_path / "orchestration.json")
    client = _client(setup_orchestration_routes(store))

    run = client.post("/api/orchestration/runs", json={"goal": "Reflector review"}).json()["run"]
    implementer, reviewer = run["plan_graph"]["tasks"][:2]
    client.post(
        f"/api/orchestration/runs/{run['id']}/tasks/{implementer['id']}/start",
        json={"scope": {"files": ["src/orchestration/store.py", "tests/test_orchestration_foundations.py"]}},
    )
    handoff = client.post(
        "/api/orchestration/handoffs",
        json={
            "run_id": run["id"],
            "from_task_id": implementer["id"],
            "to_task_id": reviewer["id"],
            "summary": "Ready but missing evidence",
            "evidence": [],
        },
    ).json()["handoff"]

    response = client.post(
        f"/api/orchestration/runs/{run['id']}/tasks/{implementer['id']}/reflector-review",
        json={
            "reviewer_profile_id": reviewer["profile_id"],
            "changed_files": [
                "src/orchestration/store.py",
                "src/unrelated.py",
            ],
            "handoff_id": handoff["id"],
            "tool_result_contracts": [
                {"tool": "grep", "output_hash": "abc", "truncated": False},
                {"tool": "edit_file", "truncated": False},
            ],
            "context_budget": {"proof": True},
            "mount_policy": {"respected": True},
            "notes": "Reflector caught drift.",
        },
    )

    assert response.status_code == 200
    review = response.json()["review"]
    assert review["passed"] is False
    gates = {gate["name"]: gate for gate in review["gates"]}
    assert gates["scope_guard"]["status"] == "fail"
    assert "src/unrelated.py" in gates["scope_guard"]["details"]["outside_scope"]
    assert gates["handoff_evidence"]["status"] == "fail"
    assert gates["tool_result_contracts"]["status"] == "fail"
    assert gates["context_budget"]["status"] == "pass"
    assert review["system_owned"] is True
    assert review["reviewer_profile_id"] == reviewer["profile_id"]

    snapshot = client.get(f"/api/orchestration/runs/{run['id']}/snapshot").json()["snapshot"]
    assert snapshot["reflector_reviews"][0]["id"] == review["id"]
    tasks = {task["id"]: task for task in snapshot["run"]["plan_graph"]["tasks"]}
    assert tasks[implementer["id"]]["quality_gate_status"] == "failed"


def test_reflector_review_passes_when_scope_handoff_and_contracts_are_valid(tmp_path):
    from routes.orchestration_routes import setup_orchestration_routes
    from src.orchestration.store import OrchestrationStore

    store = OrchestrationStore(tmp_path / "orchestration.json")
    client = _client(setup_orchestration_routes(store))

    run = client.post("/api/orchestration/runs", json={"goal": "Reflector pass"}).json()["run"]
    implementer, reviewer = run["plan_graph"]["tasks"][:2]
    client.post(
        f"/api/orchestration/runs/{run['id']}/tasks/{implementer['id']}/start",
        json={"scope": {"files": ["src/orchestration/store.py", "tests/"]}},
    )
    handoff = client.post(
        "/api/orchestration/handoffs",
        json={
            "run_id": run["id"],
            "from_task_id": implementer["id"],
            "to_task_id": reviewer["id"],
            "summary": "Ready with evidence",
            "evidence": [{"kind": "test", "ref": "pytest"}],
        },
    ).json()["handoff"]

    review = client.post(
        f"/api/orchestration/runs/{run['id']}/tasks/{implementer['id']}/reflector-review",
        json={
            "reviewer_profile_id": reviewer["profile_id"],
            "changed_files": ["src/orchestration/store.py", "tests/test_orchestration_foundations.py"],
            "handoff_id": handoff["id"],
            "tool_result_contracts": [
                {"tool": "grep", "output_hash": "abc", "truncated": False},
                {"tool": "pytest", "output_hash": "def", "truncated": False},
            ],
            "context_budget": {"proof": True},
            "mount_policy": {"respected": True},
        },
    ).json()["review"]

    assert review["passed"] is True
    assert {gate["status"] for gate in review["gates"]} == {"pass"}
    snapshot = client.get(f"/api/orchestration/runs/{run['id']}/snapshot").json()["snapshot"]
    tasks = {task["id"]: task for task in snapshot["run"]["plan_graph"]["tasks"]}
    assert tasks[implementer["id"]]["quality_gate_status"] == "passed"


def test_run_snapshot_reports_tasks_agents_handoffs_and_gates(tmp_path, monkeypatch):
    from routes.orchestration_routes import setup_orchestration_routes
    from src import bg_jobs
    from src.orchestration.store import OrchestrationStore

    jobs_dir = tmp_path / "bg_jobs"
    jobs_dir.mkdir()
    monkeypatch.setattr(bg_jobs, "_STORE", tmp_path / "bg_jobs.json")
    monkeypatch.setattr(bg_jobs, "_JOBS_DIR", jobs_dir)
    monkeypatch.setattr(bg_jobs, "_pid_alive", lambda pid: True)

    store = OrchestrationStore(tmp_path / "orchestration.json")
    client = _client(setup_orchestration_routes(store))

    run = client.post("/api/orchestration/runs", json={"goal": "Snapshot"}).json()["run"]
    implementer, reviewer = run["plan_graph"]["tasks"][:2]
    client.post(f"/api/orchestration/runs/{run['id']}/tasks/{implementer['id']}/start", json={"session_id": "s1"})
    handoff = client.post(
        "/api/orchestration/handoffs",
        json={
            "run_id": run["id"],
            "from_task_id": implementer["id"],
            "to_task_id": reviewer["id"],
            "from_profile_id": implementer["profile_id"],
            "to_profile_id": reviewer["profile_id"],
            "summary": "Snapshot handoff",
            "evidence": [{"kind": "test", "ref": "green"}],
        },
    ).json()["handoff"]
    client.post(
        "/api/orchestration/quality-gates",
        json={
            "run_id": run["id"],
            "task_id": reviewer["id"],
            "evidence": [{"kind": "test"}],
            "changed_files": ["a.py"],
            "allowed_files": ["a.py"],
            "context_budget": {"proof": True},
            "mount_policy": {"respected": True},
        },
    )
    bg_jobs._save(
        {
            "job-snapshot": {
                "id": "job-snapshot",
                "session_id": "s1",
                "run_id": run["id"],
                "task_id": implementer["id"],
                "profile_id": implementer["profile_id"],
                "agent_instance_id": implementer["agent_instance_id"],
                "status": "running",
                "pid": 123,
                "started_at": 10,
                "log_path": str(jobs_dir / "job-snapshot.log"),
                "exit_path": str(jobs_dir / "job-snapshot.exit"),
                "command": "pytest",
            }
        }
    )

    snapshot = client.get(f"/api/orchestration/runs/{run['id']}/snapshot").json()["snapshot"]
    assert snapshot["run"]["id"] == run["id"]
    assert snapshot["active_tasks"][0]["id"] == implementer["id"]
    assert snapshot["agents"][0]["profile"]["display_name"] == "Alice"
    assert snapshot["agents"][0]["jobs"][0]["id"] == "job-snapshot"
    assert snapshot["handoffs"][0]["id"] == handoff["id"]
    assert snapshot["quality_gates"][0]["passed"] is True
    assert snapshot["blocked_tasks"] == []


def test_chat_route_resolves_orchestration_context_and_attaches_session(tmp_path):
    from types import SimpleNamespace

    from routes.chat_routes import _resolve_request_orchestration_context
    from src.orchestration.store import OrchestrationStore

    store = OrchestrationStore(tmp_path / "orchestration.json")
    run = store.create_run("alice", {"goal": "Wire chat task context"})
    task = run["plan_graph"]["tasks"][0]
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(orchestration_store=store)))

    context = _resolve_request_orchestration_context(
        request,
        owner="alice",
        run_id=run["id"],
        task_id=task["id"],
        session_id="session-123",
        workspace_scope={"workspace": "G:/Programming/GitHub/odysseus"},
    )

    assert context["run_id"] == run["id"]
    assert context["task_id"] == task["id"]
    assert context["agent_profile"]["display_name"] == "Alice"
    assert context["identity"]["session_id"] == "session-123"
    assert context["identity"]["scope"]["workspace"] == "G:/Programming/GitHub/odysseus"
    assert context["capsules"][0]["kind"] == "agent_profile"


def test_disabled_profile_cannot_receive_new_run_tasks(tmp_path):
    from routes.orchestration_routes import setup_orchestration_routes
    from src.orchestration.store import OrchestrationStore

    store = OrchestrationStore(tmp_path / "orchestration.json")
    client = _client(setup_orchestration_routes(store))

    profile = client.post(
        "/api/orchestration/profiles",
        json={"display_name": "Disabled Worker", "role": "implementer", "enabled": False},
    ).json()["profile"]
    team = client.post(
        "/api/orchestration/teams",
        json={"name": "Broken Team", "members": [{"profile_id": profile["id"], "slot": "implementer"}]},
    ).json()["team"]

    response = client.post("/api/orchestration/runs", json={"goal": "Do work", "team_id": team["id"]})
    assert response.status_code == 400
    assert "disabled" in response.json()["detail"]


def test_mount_registry_validates_owner_scope_and_write_policy(tmp_path):
    from src.workspaces.mounts import MountRegistry, MountPolicyError

    project = tmp_path / "project"
    project.mkdir()
    source = project / "main.py"
    source.write_text("print('hello')\n", encoding="utf-8")

    registry = MountRegistry(tmp_path / "mounts.json")
    mount = registry.create_mount(
        owner="alice",
        name="Project",
        root=str(project),
        write_policy="backup",
        extension_allowlist=[".py", ".md"],
        max_file_bytes=64,
    )

    assert registry.list_mounts("alice")[0]["id"] == mount["id"]
    assert registry.list_mounts("bob") == []
    assert registry.resolve_access("alice", mount["id"], "main.py", operation="read") == os.path.realpath(source)

    with pytest.raises(MountPolicyError):
        registry.resolve_access("alice", mount["id"], "../escape.py", operation="read")
    with pytest.raises(MountPolicyError):
        registry.resolve_access("bob", mount["id"], "main.py", operation="read")
    with pytest.raises(MountPolicyError):
        registry.resolve_access("alice", mount["id"], "tool.exe", operation="write")

    large = project / "big.py"
    large.write_text("x" * 128, encoding="utf-8")
    with pytest.raises(MountPolicyError):
        registry.resolve_access("alice", mount["id"], "big.py", operation="read")

    backup = registry.backup_before_overwrite("alice", mount["id"], "main.py")
    assert backup is not None
    assert os.path.exists(backup["backup_path"])
    assert backup["original_path"] == os.path.realpath(source)


def test_mount_routes_create_list_and_report_denied_access(tmp_path, monkeypatch):
    from routes.workspace_mount_routes import setup_workspace_mount_routes
    from src.workspaces.mounts import MountRegistry

    project = tmp_path / "project"
    project.mkdir()
    (project / "app.py").write_text("print('ok')\n", encoding="utf-8")
    registry = MountRegistry(tmp_path / "mounts.json")
    client = _client(setup_workspace_mount_routes(registry))

    monkeypatch.setattr("routes.workspace_mount_routes.effective_user", lambda request: "alice")
    mount = client.post(
        "/api/workspaces/mounts",
        json={
            "name": "Project",
            "root": str(project),
            "write_policy": "backup",
            "extension_allowlist": [".py"],
            "max_file_bytes": 1000,
        },
    ).json()["mount"]

    assert client.get("/api/workspaces/mounts").json()["mounts"][0]["id"] == mount["id"]

    ok = client.post(
        f"/api/workspaces/mounts/{mount['id']}/resolve",
        json={"path": "app.py", "operation": "read"},
    ).json()
    assert ok["ok"] is True
    assert ok["path"].endswith("app.py")

    denied = client.post(
        f"/api/workspaces/mounts/{mount['id']}/resolve",
        json={"path": "secret.exe", "operation": "write"},
    ).json()
    assert denied["ok"] is False
    assert "not allowed" in denied["error"]


def test_context_diagnostics_route_reports_budget_capsules_and_truth_contracts():
    from routes.context_routes import setup_context_routes

    client = _client(setup_context_routes())
    response = client.post(
        "/api/context/diagnostics",
        json={
            "configured_budget": 6000,
            "context_length": 10000,
            "explicit_budget": False,
            "capsules": [
                {"kind": "project_state", "tokens": 100, "included": True},
                {"kind": "memory_summary", "tokens": 200, "included": False, "reason": "budget"},
            ],
            "tool_results": [
                {"tool": "grep", "output": "abc" * 100, "mount_id": "m1", "truncated": True}
            ],
        },
    )

    body = response.json()
    assert body["effective_budget"] == 8500
    assert body["included_capsules"] == ["project_state"]
    assert body["omitted_capsules"][0]["kind"] == "memory_summary"
    contract = body["tool_result_contracts"][0]
    assert contract["tool"] == "grep"
    assert contract["output_hash"]
    assert contract["bounded_excerpt"].startswith("abc")
    assert contract["truncated"] is True


def test_jobs_route_lists_inspects_and_stops_jobs(tmp_path, monkeypatch):
    from routes.job_routes import setup_job_routes
    from src import bg_jobs

    jobs_dir = tmp_path / "bg_jobs"
    jobs_dir.mkdir()
    monkeypatch.setattr(bg_jobs, "_STORE", tmp_path / "bg_jobs.json")
    monkeypatch.setattr(bg_jobs, "_JOBS_DIR", jobs_dir)
    monkeypatch.setattr(bg_jobs, "_pid_alive", lambda pid: True)
    killed = []
    monkeypatch.setattr(bg_jobs, "_kill", lambda pid: killed.append(pid))

    log = jobs_dir / "job1.log"
    exit_path = jobs_dir / "job1.exit"
    log.write_text("line 1\nline 2\n", encoding="utf-8")
    bg_jobs._save(
        {
            "job1": {
                "id": "job1",
                "session_id": "s1",
                "run_id": "r1",
                "profile_id": "p1",
                "status": "running",
                "pid": 123,
                "cwd": str(tmp_path),
                "command": "pytest",
                "started": 10,
                "log_path": str(log),
                "exit_path": str(exit_path),
            }
        }
    )

    client = _client(setup_job_routes())
    listing = client.get("/api/jobs?run_id=r1&profile_id=p1").json()["jobs"]
    assert listing[0]["id"] == "job1"
    assert listing[0]["output_tail"].endswith("line 2")

    detail = client.get("/api/jobs/job1").json()["job"]
    assert detail["cwd"] == str(tmp_path)

    stopped = client.post("/api/jobs/job1/stop").json()["job"]
    assert stopped["status"] == "killed"
    assert killed == [123]


def test_memory_stats_and_progressive_graph_routes(tmp_path):
    from routes.memory_graph_routes import setup_memory_graph_routes
    from src.memory_graph.maintenance import MemoryMaintenanceStore
    from src.memory_graph.store import MemoryGraphStore

    memory_manager = SimpleNamespace(
        load_all=lambda: [
            {"owner": "alice", "category": "preference", "source": "user"},
            {"owner": "alice", "category": "project", "source": "agent"},
            {"owner": "bob", "category": "preference", "source": "user"},
        ]
    )
    memory_vector = SimpleNamespace(healthy=True, count=lambda: 3)
    graph = MemoryGraphStore(tmp_path / "graph.json")
    graph.add_node("n1", owner="alice", kind="memory", label="Preference")
    graph.add_node("n2", owner="alice", kind="project", label="Project")
    graph.add_node("n3", owner="alice", kind="summary", label="Summary")
    graph.add_edge("n1", "n2", owner="alice", relation="supports")
    graph.add_edge("n1", "n3", owner="alice", relation="derived")
    maintenance = MemoryMaintenanceStore(tmp_path / "maintenance.json")

    client = _client(setup_memory_graph_routes(memory_manager, memory_vector, graph, maintenance))
    stats = client.get("/api/memory/stats").json()
    assert stats["total"] == 3
    assert stats["by_owner"]["alice"] == 2
    assert stats["vector"]["healthy"] is True
    assert stats["vector"]["count"] == 3

    created = client.post(
        "/api/memory/maintenance/runs",
        json={
            "owner": "alice",
            "kind": "evidence_summary",
            "source_ids": ["m1", "m2"],
            "summary": "Alice prefers scoped evidence.",
            "evidence": [{"kind": "tool_result", "ref": "hash-1"}],
            "proof": {"algorithm": "evidence-bound-summary", "input_count": 2},
        },
    ).json()["run"]
    assert created["status"] == "complete"
    assert created["evidence"][0]["ref"] == "hash-1"

    maintenance_runs = client.get("/api/memory/maintenance/runs?owner=alice").json()["runs"]
    assert maintenance_runs[0]["id"] == created["id"]

    neighborhood = client.get("/api/graph/neighborhood?owner=alice&node_id=n1&budget=2").json()
    assert {node["id"] for node in neighborhood["nodes"]} == {"n1", "n2"}
    assert neighborhood["edges"][0]["relation"] == "supports"
    assert neighborhood["proof"] == {
        "requested_budget": 2,
        "effective_budget": 2,
        "included_nodes": 2,
        "included_edges": 1,
        "omitted_nodes": 1,
        "truncated": True,
    }


def test_memory_maintenance_store_persists_evidence_bound_runs(tmp_path):
    from src.memory_graph.maintenance import MemoryMaintenanceStore

    path = tmp_path / "maintenance.json"
    store = MemoryMaintenanceStore(path)
    run = store.create_run(
        {
            "owner": "alice",
            "kind": "cluster_run",
            "source_ids": ["m1"],
            "summary": "Clustered memory.",
            "evidence": [{"kind": "memory", "id": "m1"}],
            "proof": {"algorithm": "k-means", "k": 1},
        }
    )

    reloaded = MemoryMaintenanceStore(path)
    runs = reloaded.list_runs("alice")
    assert runs[0]["id"] == run["id"]
    assert runs[0]["evidence_bound"] is True
    assert runs[0]["proof"]["algorithm"] == "k-means"
    assert reloaded.list_runs("bob") == []
