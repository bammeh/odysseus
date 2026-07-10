# Odysseus Plugin Platform

Odysseus plugins are trusted, admin-installed Python bundles. A plugin can add:

- FastAPI routes under `/api/plugins/{plugin_id}/...`
- Agent tools named `plugin__{plugin_id}__{tool_name}`
- Sandboxed app panels loaded from `/plugins/{plugin_id}/static/...`
- Context providers and jobs through the plugin runtime registration context

## Folder Shape

```text
my_plugin/
  odysseus.plugin.json
  plugin.py
  panel.html
```

See `examples/plugins/demo_plugin` for a complete plugin that passes policy validation and exercises a panel, FastAPI route, and agent tool.

Agents creating plugins should read `docs/agents/plugin-authoring.md`; repo-level guidance also points to this from `AGENTS.md`.

`odysseus.plugin.json`:

```json
{
  "id": "my_plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "description": "Adds a small panel and tool.",
  "entrypoint": "plugin.py",
  "permissions": ["local-files:read"],
  "dependencies": [],
  "panels": [
    { "id": "main", "title": "My Plugin", "path": "panel.html", "width": 760, "height": 520 }
  ],
  "tools": [
    {
      "name": "echo",
      "description": "Echo text back to the agent.",
      "parameters": {
        "type": "object",
        "properties": { "text": { "type": "string" } }
      },
      "read_only": true
    }
  ]
}
```

`plugin.py`:

```python
from fastapi import APIRouter


def register_plugin(context):
    router = APIRouter()

    @router.get("/health")
    def health():
        return {"ok": True}

    context.register_router(router)
    context.register_tool("echo", lambda args, ctx: {"echo": args.get("text", "")})
```

## Admin Flow

Install a local plugin folder:

```http
POST /api/plugins/install/local
{ "path": "C:/path/to/my_plugin" }
```

Installed plugins are considered valid when they pass manifest validation and the
plugin-system guards. Admins can pause a valid plugin globally without uninstalling it:

```http
POST /api/plugins/my_plugin/global-enable
{ "enabled": false }
```

Audit installed plugins:

```http
GET /api/plugins/audit
```

Record a GitHub candidate for review:

```http
POST /api/plugins/install/github
{ "repo_url": "https://github.com/org/repo", "subpath": "plugins/my_plugin" }
```

V1 records GitHub candidates for audit. Downloading and dependency installation should remain gated by the plugin system's validation rules.

## User Flow

Users opt in per plugin:

```http
POST /api/plugins/my_plugin/enable
{ "enabled": true }
```

Enabled plugin panels are listed at:

```http
GET /api/plugins/panels
```

The frontend exposes:

```js
window.odysseusPlugins.openPanel('my_plugin', 'main')
```

Panels are movable/resizable Odysseus windows containing sandboxed iframes.

Panels can communicate with Odysseus through a narrow `postMessage` bridge. Supported actions are:

- `toast` - show an Odysseus toast.
- `resize` - request a bounded panel size.
- `close` - close the panel.
- `refresh` - reload the panel iframe.
- `pluginApi` - call this plugin's own `/api/plugins/{plugin_id}/...` routes.

The bridge only accepts messages from the iframe belonging to the panel and `pluginApi` URLs must stay inside the panel's own plugin namespace.

## Capability Boundaries

- Plugin IDs, tool names, and panel IDs must be lowercase slugs.
- Manifest paths are confined to the plugin folder.
- Plugins are trusted Python code. Installing one is equivalent to installing an app extension.
- Newly installed plugins must pass manifest validation and plugin-system guards.
- Global disable overrides per-user opt-in.
- Per-user opt-in controls visibility of panels and agent-callable tools.
- Dangerous host capabilities should be represented in `permissions` and reviewed through `/api/plugins/audit`.

## Manifest Policy

The plugin system validates manifests before installing or exposing a plugin:

- `id` must be a lowercase slug using letters, numbers, `_`, or `-`.
- Panel IDs and tool names must be lowercase slugs.
- `entrypoint` and panel paths must stay inside the plugin folder.
- Panel files must exist before panels are exposed.
- Tool parameter schemas must be JSON objects.
- Permissions must be lowercase names such as `network:http` or `files:read`.
- Dependencies must be plain package specs such as `httpx==0.28.1` or `pydantic>=2.0`.
- Dependency specs cannot be local paths, URLs, editable installs, shell fragments, or direct file references.
- Plugin routes are always mounted under `/api/plugins/{plugin_id}`.

Validation is available through:

```http
GET /api/plugins/my_plugin/validation
```

Settings shows invalid plugins with the failed rule codes and hides their panels/tools until the manifest satisfies the policy.
