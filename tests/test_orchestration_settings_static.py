from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_settings_has_orchestration_admin_tab_and_panel():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

    assert 'data-settings-tab="orchestration"' in html
    assert "<span>Orchestration</span>" in html
    assert 'data-settings-panel="orchestration"' in html
    assert 'id="settings-orchestration-profile-list"' in html
    assert 'id="settings-orchestration-profile-name"' in html
    assert 'id="settings-orchestration-profile-role"' in html
    assert 'id="settings-orchestration-profile-template"' in html
    assert 'id="settings-orchestration-profile-create-btn"' in html
    assert 'id="settings-orchestration-team-list"' in html
    assert 'id="settings-orchestration-team-name"' in html
    assert 'id="settings-orchestration-team-implementer"' in html
    assert 'id="settings-orchestration-team-reviewer"' in html
    assert 'id="settings-orchestration-team-integrator"' in html
    assert 'id="settings-orchestration-team-create-btn"' in html
    assert 'id="settings-orchestration-run-list"' in html
    assert 'id="settings-orchestration-job-list"' in html
    assert 'id="settings-orchestration-mount-list"' in html
    assert 'id="settings-orchestration-memory-stats"' in html
    assert 'id="settings-orchestration-maintenance-list"' in html


def test_settings_js_initializes_orchestration_tab():
    js = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")

    assert "initOrchestrationSettings" in js
    assert "renderOrchestrationSettings" in js
    assert "createOrchestrationProfile" in js
    assert "duplicateOrchestrationProfile" in js
    assert "toggleOrchestrationProfile" in js
    assert "deleteOrchestrationProfile" in js
    assert "createOrchestrationTeam" in js
    assert "duplicateOrchestrationTeam" in js
    assert "toggleOrchestrationTeam" in js
    assert "deleteOrchestrationTeam" in js
    assert "/api/orchestration/profiles" in js
    assert "/api/orchestration/profile-templates" in js
    assert "/api/orchestration/profiles/${profileId}/duplicate" in js
    assert "/api/orchestration/teams" in js
    assert "/api/orchestration/teams/${teamId}/duplicate" in js
    assert "/api/orchestration/runs" in js
    assert "/api/jobs" in js
    assert "/api/workspaces/mounts" in js
    assert "/api/memory/stats" in js
    assert "/api/memory/maintenance/runs" in js
