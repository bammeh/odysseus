from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_settings_has_orchestration_admin_tab_and_panel():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

    assert 'data-settings-tab="orchestration"' in html
    assert "<span>Orchestration</span>" in html
    assert 'data-settings-panel="orchestration"' in html
    assert 'id="settings-orchestration-profile-list"' in html
    assert 'id="settings-orchestration-team-list"' in html
    assert 'id="settings-orchestration-run-list"' in html
    assert 'id="settings-orchestration-job-list"' in html
    assert 'id="settings-orchestration-mount-list"' in html
    assert 'id="settings-orchestration-memory-stats"' in html
    assert 'id="settings-orchestration-maintenance-list"' in html


def test_settings_js_initializes_orchestration_tab():
    js = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")

    assert "initOrchestrationSettings" in js
    assert "renderOrchestrationSettings" in js
    assert "/api/orchestration/profiles" in js
    assert "/api/orchestration/teams" in js
    assert "/api/orchestration/runs" in js
    assert "/api/jobs" in js
    assert "/api/workspaces/mounts" in js
    assert "/api/memory/stats" in js
    assert "/api/memory/maintenance/runs" in js
