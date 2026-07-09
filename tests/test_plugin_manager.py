import json

from src.plugins.manager import PluginManager


def make_plugin(path, plugin_id="demo_plugin"):
    path.mkdir()
    (path / "plugin.py").write_text(
        """
def register_plugin(context):
    context.register_tool("echo", lambda args, ctx: {"echo": args.get("text")})
""".strip(),
        encoding="utf-8",
    )
    (path / "odysseus.plugin.json").write_text(
        json.dumps(
            {
                "id": plugin_id,
                "name": "Demo Plugin",
                "version": "1.0.0",
                "entrypoint": "plugin.py",
                "panels": [{"id": "main", "title": "Demo", "path": "panel.html"}],
                "tools": [
                    {
                        "name": "echo",
                        "description": "Echo text",
                        "parameters": {
                            "type": "object",
                            "properties": {"text": {"type": "string"}},
                        },
                        "read_only": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (path / "panel.html").write_text("<h1>Demo</h1>", encoding="utf-8")
    return path


def test_manager_discovers_plugins_and_requires_user_opt_in(tmp_path):
    plugins_dir = tmp_path / "plugins"
    state_file = tmp_path / "plugins.json"
    make_plugin(plugins_dir / "demo_plugin")

    manager = PluginManager(root=plugins_dir, state_file=state_file)
    manager.discover()

    assert [plugin.id for plugin in manager.list_plugins()] == ["demo_plugin"]
    assert manager.list_panels_for_user("alice") == []

    manager.set_user_enabled("alice", "demo_plugin", True)

    panels = manager.list_panels_for_user("alice")
    assert panels[0]["plugin_id"] == "demo_plugin"
    assert panels[0]["iframe_url"] == "/plugins/demo_plugin/static/panel.html"


def test_manager_registers_plugin_tools_after_user_opt_in(tmp_path):
    plugins_dir = tmp_path / "plugins"
    state_file = tmp_path / "plugins.json"
    make_plugin(plugins_dir / "demo_plugin")

    manager = PluginManager(root=plugins_dir, state_file=state_file)
    manager.discover()
    manager.set_user_enabled("alice", "demo_plugin", True)

    tools = manager.list_tool_schemas_for_user("alice")
    assert tools[0]["function"]["name"] == "plugin__demo_plugin__echo"

    result = manager.execute_tool("plugin__demo_plugin__echo", {"text": "hello"}, {"owner": "alice"})
    assert result == {"echo": "hello"}
