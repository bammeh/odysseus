import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.plugin_routes import setup_plugin_routes
from src.plugins.manager import PluginManager


def make_plugin(path):
    path.mkdir(parents=True)
    (path / "plugin.py").write_text("def register_plugin(context):\n    pass\n", encoding="utf-8")
    (path / "odysseus.plugin.json").write_text(
        json.dumps(
            {
                "id": "demo_plugin",
                "name": "Demo Plugin",
                "version": "1.0.0",
                "entrypoint": "plugin.py",
                "panels": [{"id": "main", "title": "Demo", "path": "panel.html"}],
            }
        ),
        encoding="utf-8",
    )
    (path / "panel.html").write_text("<h1>Demo</h1>", encoding="utf-8")


def build_client(tmp_path):
    plugins_dir = tmp_path / "plugins"
    make_plugin(plugins_dir / "demo_plugin")
    manager = PluginManager(root=plugins_dir, state_file=tmp_path / "plugins.json")
    manager.discover()
    app = FastAPI()
    app.include_router(setup_plugin_routes(manager))
    return TestClient(app)


def test_plugin_routes_list_plugins_with_user_enabled_state(tmp_path):
    client = build_client(tmp_path)

    response = client.get("/api/plugins", headers={"x-test-user": "alice"})

    assert response.status_code == 200
    assert response.json()[0]["id"] == "demo_plugin"
    assert response.json()[0]["enabled_for_user"] is False


def test_plugin_routes_enable_plugin_and_list_panels(tmp_path):
    client = build_client(tmp_path)

    response = client.post("/api/plugins/demo_plugin/enable", json={"enabled": True}, headers={"x-test-user": "alice"})
    assert response.status_code == 200

    panels = client.get("/api/plugins/panels", headers={"x-test-user": "alice"}).json()
    assert panels[0]["plugin_id"] == "demo_plugin"
    assert panels[0]["iframe_url"] == "/plugins/demo_plugin/static/panel.html"
