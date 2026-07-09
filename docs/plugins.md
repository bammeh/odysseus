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

Audit installed plugins:

```http
GET /api/plugins/audit
```

Record a GitHub candidate for review:

```http
POST /api/plugins/install/github
{ "repo_url": "https://github.com/org/repo", "subpath": "plugins/my_plugin" }
```

V1 records GitHub candidates for audit. Downloading and dependency installation should remain an admin-approved release gate.

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

## Capability Boundaries

- Plugin IDs, tool names, and panel IDs must be lowercase slugs.
- Manifest paths are confined to the plugin folder.
- Plugins are trusted Python code. Installing one is equivalent to installing an app extension.
- Per-user opt-in controls visibility of panels and agent-callable tools.
- Dangerous host capabilities should be represented in `permissions` and reviewed through `/api/plugins/audit`.
