import json

import pytest

from src.plugins.manifest import PluginManifest, PluginManifestError


def write_manifest(path, payload):
    manifest_path = path / "odysseus.plugin.json"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    return manifest_path


def test_manifest_normalizes_plugin_panels_and_tools(tmp_path):
    manifest_path = write_manifest(
        tmp_path,
        {
            "id": "calendar_plus",
            "name": "Calendar Plus",
            "version": "1.2.3",
            "description": "Extra calendar views",
            "entrypoint": "plugin.py",
            "panels": [
                {
                    "id": "timeline",
                    "title": "Timeline",
                    "path": "panel/index.html",
                    "width": 820,
                    "height": 560,
                }
            ],
            "tools": [
                {
                    "name": "summarize_day",
                    "description": "Summarize a user's day",
                    "parameters": {"type": "object", "properties": {}},
                    "read_only": True,
                }
            ],
        },
    )

    manifest = PluginManifest.from_file(manifest_path)

    assert manifest.id == "calendar_plus"
    assert manifest.entrypoint == tmp_path / "plugin.py"
    assert manifest.panels[0].iframe_url == "/plugins/calendar_plus/static/panel/index.html"
    assert manifest.panels[0].width == 820
    assert manifest.tools[0].qualified_name == "plugin__calendar_plus__summarize_day"
    assert manifest.tools[0].schema["function"]["name"] == "plugin__calendar_plus__summarize_day"


@pytest.mark.parametrize(
    "plugin_id",
    ["../escape", "has.dot", "UpperCase", "space name", ""],
)
def test_manifest_rejects_unsafe_plugin_ids(tmp_path, plugin_id):
    manifest_path = write_manifest(
        tmp_path,
        {
            "id": plugin_id,
            "name": "Bad",
            "version": "1.0.0",
            "entrypoint": "plugin.py",
        },
    )

    with pytest.raises(PluginManifestError):
        PluginManifest.from_file(manifest_path)


def test_manifest_rejects_panel_paths_outside_plugin(tmp_path):
    manifest_path = write_manifest(
        tmp_path,
        {
            "id": "bad_panel",
            "name": "Bad Panel",
            "version": "1.0.0",
            "entrypoint": "plugin.py",
            "panels": [{"id": "main", "title": "Main", "path": "../secret.html"}],
        },
    )

    with pytest.raises(PluginManifestError):
        PluginManifest.from_file(manifest_path)
