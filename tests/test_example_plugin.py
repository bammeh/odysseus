from pathlib import Path

from src.plugins.manifest import PluginManifest
from src.plugins.manager import PluginManager


ROOT = Path(__file__).resolve().parents[1]


def test_example_demo_plugin_passes_policy_and_exposes_surfaces(tmp_path):
    source = ROOT / "examples" / "plugins" / "demo_plugin"
    manifest = PluginManifest.from_file(source / "odysseus.plugin.json")

    assert manifest.id == "demo_plugin"
    assert manifest.panels[0].iframe_url == "/plugins/demo_plugin/static/panel.html"
    assert manifest.tools[0].qualified_name == "plugin__demo_plugin__echo"

    manager = PluginManager(root=source.parent, state_file=tmp_path / "plugins.json")
    manager.discover()
    report = manager.validation_report("demo_plugin")
    assert report["valid"] is True

    manager.set_user_enabled("alice", "demo_plugin", True)
    assert manager.list_panels_for_user("alice")[0]["plugin_id"] == "demo_plugin"
    assert manager.execute_tool(
        "plugin__demo_plugin__echo",
        {"text": "hello"},
        {"owner": "alice"},
    )["echo"] == "hello"
