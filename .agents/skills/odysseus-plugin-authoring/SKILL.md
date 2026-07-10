---
name: odysseus-plugin-authoring
description: Create, edit, review, or test Odysseus AI plugins, including odysseus.plugin.json manifests, plugin.py register_plugin entrypoints, plugin-owned FastAPI routes, agent tools, sandboxed plugin panels, validation policy, dependency guards, and Settings plugin UI.
---

# Odysseus Plugin Authoring

Before creating or editing plugins, read `docs/agents/plugin-authoring.md`.

Use `examples/plugins/demo_plugin` as the reference implementation.

Core rules:

- Plugins are valid when they pass plugin-system policy rules; do not add approve/reject workflows.
- Invalid plugins must not expose panels or agent tools.
- Global enablement and per-user opt-in are separate gates.
- Plugin routes must stay under `/api/plugins/{plugin_id}`.
- Plugin tools must be named `plugin__{plugin_id}__{tool_name}` by the platform.
- Panel files must be served from `/plugins/{plugin_id}/static/...` and loaded in sandboxed iframes.
- Panels should use the `odysseus:plugin` postMessage bridge for toasts, resize, close, refresh, and plugin API calls.
- Plugin API bridge calls must stay under `/api/plugins/{plugin_id}/...` for the panel's own plugin.
- Dependencies must be plain package specs, never URLs, local paths, editable installs, or shell fragments.

Verification:

- Compile touched plugin backend files.
- Validate the example plugin with `PluginManager.validation_report`.
- Run focused pytest plugin tests when pytest is available.
