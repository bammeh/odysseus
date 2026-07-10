from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_settings_has_plugins_admin_tab_and_panel():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

    assert 'data-settings-tab="plugins"' in html
    assert "<span>Plugins</span>" in html
    assert 'data-settings-panel="plugins"' in html
    assert 'id="settings-plugin-list"' in html
    assert 'id="settings-plugin-install-path"' in html


def test_settings_js_initializes_plugins_tab():
    js = (ROOT / "static" / "js" / "settings.js").read_text(encoding="utf-8")

    assert "initPluginSettings" in js
    assert "renderPluginSettings" in js
    assert "/api/plugins" in js
    assert "odysseusPlugins.openPanel" in js


def test_plugin_panel_bridge_is_exposed_and_namespaced():
    js = (ROOT / "static" / "js" / "plugins.js").read_text(encoding="utf-8")
    html = (ROOT / "examples" / "plugins" / "demo_plugin" / "panel.html").read_text(encoding="utf-8")

    assert "odysseus:plugin" in js
    assert "handlePluginBridgeMessage" in js
    assert "pluginApi" in js
    assert "event.source !== panel.iframe.contentWindow" in js
    assert "url.startsWith(`/api/plugins/${pluginId}/`)" in js
    assert "window.parent.postMessage" in html
    assert "odysseus:plugin" in html
