# Odysseus Plugin Authoring For Agents

Use this guide when an AI agent is asked to create, edit, review, or test Odysseus plugins.

## Required Shape

```text
plugin_folder/
  odysseus.plugin.json
  plugin.py
  panel.html
```

The manifest file must be named exactly `odysseus.plugin.json`.

## Validation Model

Plugins are not manually approved or rejected. A plugin is usable when it passes the plugin-system policy rules.

Policy failures make the plugin invalid. Invalid plugins can still be listed in Settings, but they must not expose panels or agent tools.

## Manifest Rules

- `id`, panel IDs, and tool names must be lowercase slugs.
- `entrypoint` and panel paths must stay inside the plugin folder.
- Panel files must exist.
- Tool parameter schemas must be JSON objects.
- Permissions must be lowercase names like `network:http` or `files:read`.
- Dependencies must be plain package specs like `httpx==0.28.1`.
- Do not use dependency URLs, local paths, editable installs, shell fragments, or direct file references.

## Runtime Pattern

```python
from fastapi import APIRouter


def register_plugin(context):
    router = APIRouter()

    @router.get("/health")
    def health():
        return {"ok": True}

    def echo(args, ctx):
        return {"echo": args.get("text", "")}

    context.register_router(router)
    context.register_tool("echo", echo)
```

Plugin routes are mounted under `/api/plugins/{plugin_id}`. If a plugin registers `@router.get("/health")`, the final route is `/api/plugins/{plugin_id}/health`.

Plugin tools are exposed as `plugin__{plugin_id}__{tool_name}`.

## UI Pattern

Panels are declared in the manifest and loaded from `/plugins/{plugin_id}/static/{path}` in a sandboxed iframe. Do not require same-origin iframe privileges.

Use `examples/plugins/demo_plugin` as the reference panel implementation.

Panel code should use the parent `postMessage` bridge instead of direct same-origin access. Send messages shaped like:

```js
window.parent.postMessage({
  type: 'odysseus:plugin',
  version: 1,
  requestId: 'unique-id',
  action: 'pluginApi',
  payload: { method: 'GET', url: '/api/plugins/my_plugin/health' }
}, '*');
```

Supported parent actions are `toast`, `resize`, `close`, `refresh`, and `pluginApi`. `pluginApi` requests must stay under `/api/plugins/{plugin_id}/...` for the panel's own plugin.

## Verification

At minimum, run:

```powershell
python -m py_compile src\plugins\policy.py src\plugins\manifest.py src\plugins\manager.py routes\plugin_routes.py
```

If pytest is available, run focused plugin tests:

```powershell
python -m pytest tests/test_plugin_manifest.py tests/test_plugin_manager.py tests/test_plugin_routes.py tests/test_plugin_settings_static.py
```

If pytest is unavailable, run a direct smoke test that loads a temporary plugin, checks validation, enables it for a user, lists panels, and executes a plugin tool.
