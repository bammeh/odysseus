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
    graph.add_edge("n1", "n2", owner="alice", relation="supports")

    client = _client(setup_memory_graph_routes(memory_manager, memory_vector, graph))
    stats = client.get("/api/memory/stats").json()
    assert stats["total"] == 3
    assert stats["by_owner"]["alice"] == 2
    assert stats["vector"]["healthy"] is True
    assert stats["vector"]["count"] == 3

    neighborhood = client.get("/api/graph/neighborhood?owner=alice&node_id=n1&budget=5").json()
    assert {node["id"] for node in neighborhood["nodes"]} == {"n1", "n2"}
    assert neighborhood["edges"][0]["relation"] == "supports"
